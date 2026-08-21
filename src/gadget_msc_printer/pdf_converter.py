from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import warnings
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from .config import PdfConfig
from .document_formats import (
    declared_pjl_language,
    detect_c_printer_protocol,
    detect_escp2_profile_hint,
    detect_epson_protocol,
    detect_image_format,
    detect_modern_print_format,
    detect_xps_package,
    looks_like_hpgl,
    looks_like_pcl3gui,
)
from .escpr import EscprDecodeError, decode_escpr
from .private_raster import (
    PrivateRasterSpec,
    detect_private_raster,
    private_raster_dpi,
    private_raster_transform,
)
from .prn_analyzer import C_GROUP_PROTOCOL_IDS, PROTOCOL_LABELS

LOGGER = logging.getLogger(__name__)
ACL_FIRMWARE_MARKER = b"AGIACLDOWNLOAD"
PRIVATE_RASTER_PROBE_BYTES = 1024 * 1024
MAX_PRIVATE_RASTER_PAGES = 100
MAX_PRIVATE_RASTER_PAGE_PIXELS = 75_000_000
MAX_PRIVATE_RASTER_SOURCE_PIXELS = 150_000_000
MAX_PRIVATE_RASTER_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_PRIVATE_RASTER_OUTPUT_DPI = 600
MAX_IMAGE_PAGES = 100
MAX_IMAGE_PAGE_PIXELS = 75_000_000
MAX_IMAGE_TOTAL_PIXELS = 100_000_000
PRIVATE_RASTER_TIMEOUT_SECONDS = 120
DOCUMENT_CONVERSION_TIMEOUT_SECONDS = 180
PWG_TO_PDF = "/usr/lib/cups/filter/pwgtopdf"
PRIVATE_PAGE_PATTERN = re.compile(
    r"^page-(\d+)(?:-(\d+)(?:-(\d+))?)?\.(?:pbm|pgm|ppm)$",
    re.IGNORECASE,
)
ESCP_TRAILER_PROBE_BYTES = 4096
ESCP_RESET = b"\x1b@"
ESCP_UEL = b"\x1b%-12345X"
ESCP_REMOTE_PREFIX = b"\x1b(R\x08\x00\x00REMOTE1"
ESCP_REMOTE_COMMANDS = {
    b"IR": (2, b"\x00\x00"),
    b"LD": (0, b""),
    b"JE": (1, b"\x00"),
}
ESCAPY_PROFILE_CONFIG_ROOT = Path("/etc/jvlei-escapy")


class PdfConverter:
    def __init__(self, config: PdfConfig) -> None:
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.last_error = ""
        self.last_outcome = "failed"
        self.last_escp2_profile = ""

    def convert(self, source: str | Path, source_type: str) -> Path | None:
        self.last_error = ""
        self.last_outcome = "failed"
        self.last_escp2_profile = ""
        if not self.config.enabled:
            self.last_error = "PDF conversion is disabled"
            self.last_outcome = "disabled"
            return None
        path = Path(source)
        if not path.is_file():
            self.last_error = f"source missing: {path}"
            LOGGER.warning("source missing: %s", path)
            return None
        ignored = self.ignore_reason(path)
        if ignored:
            self.last_error = ignored
            self.last_outcome = "ignored"
            LOGGER.info("ignore non-report print stream: %s reason=%s", path, ignored)
            return None
        target = self._target_path(path, source_type)
        try:
            probe = self._probe(path)
            c_protocol = detect_c_printer_protocol(probe)
            private_raster = detect_private_raster(probe)
            xps_protocol = detect_xps_package(path)
            modern_protocol = detect_modern_print_format(probe)
            epson_protocol = detect_epson_protocol(probe)
            image_format = detect_image_format(probe)
            if modern_protocol == "pclm":
                # PCLm is already a PDF-based print stream. Keeping the original
                # bytes preserves the driver's page and raster settings.
                shutil.copyfile(path, target)
            elif modern_protocol in {"pwg_raster", "cups_raster", "apple_urf"}:
                label = {
                    "pwg_raster": "PWG Raster",
                    "cups_raster": "CUPS Raster",
                    "apple_urf": "Apple URF",
                }[modern_protocol]
                if not self._driverless_raster_to_pdf(path, target, label):
                    target.unlink(missing_ok=True)
                    return None
            elif self._is_pdf(path):
                # FAT timestamps are local-time values and can appear hours in the
                # future on a UTC board. The generated report must use board time.
                shutil.copyfile(path, target)
            elif xps_protocol:
                if not self._xps_to_pdf(path, target):
                    target.unlink(missing_ok=True)
                    return None
            elif self._is_postscript(path):
                if not self._ps_to_pdf(path, target):
                    target.unlink(missing_ok=True)
                    return None
            elif image_format:
                if not self._image_to_pdf(path, target, image_format.upper()):
                    target.unlink(missing_ok=True)
                    return None
            elif c_protocol:
                self.last_error = (
                    f"识别为{PROTOCOL_LABELS.get(c_protocol, c_protocol)}，"
                    "当前仅保留原始PRN，不生成PDF"
                )
                self.last_outcome = "retained"
                target.unlink(missing_ok=True)
                return None
            elif private_raster:
                if private_raster.protocol in C_GROUP_PROTOCOL_IDS:
                    self.last_error = (
                        f"识别为{private_raster.label}，当前仅保留原始PRN，不生成PDF"
                    )
                    self.last_outcome = "retained"
                    target.unlink(missing_ok=True)
                    return None
                if not self._private_raster_to_pdf(path, target, private_raster):
                    target.unlink(missing_ok=True)
                    return None
            elif looks_like_pcl3gui(probe):
                self.last_error = (
                    "识别为PCL3/PCL3GUI，现有GhostPCL无法可靠还原页面；"
                    "已保留原始PRN，不生成PDF"
                )
                self.last_outcome = "retained"
                target.unlink(missing_ok=True)
                return None
            elif epson_protocol == "escpr":
                if not self._escpr_to_pdf(path, target):
                    target.unlink(missing_ok=True)
                    return None
            elif epson_protocol in {"escp", "escp2"}:
                if not self._escp_to_pdf(path, target, epson_protocol, probe):
                    target.unlink(missing_ok=True)
                    return None
            elif epson_protocol:
                self.last_error = (
                    f"识别为{PROTOCOL_LABELS.get(epson_protocol, epson_protocol)}，"
                    "当前没有可靠PDF转换器；已保留原始PRN"
                )
                self.last_outcome = "retained"
                target.unlink(missing_ok=True)
                return None
            elif looks_like_hpgl(probe):
                if not self._pcl_to_pdf(path, target, "HP-GL/2"):
                    target.unlink(missing_ok=True)
                    return None
            elif self._is_pcl(path):
                if not self._pcl_to_pdf(path, target, "PCL/PCL XL"):
                    target.unlink(missing_ok=True)
                    return None
            elif self._image_to_pdf(path, target):
                pass
            elif self._text_to_pdf(path, target):
                pass
            else:
                self.last_error = "无法识别可转换格式；已保留原始文件，不生成PDF"
                self.last_outcome = "retained"
                LOGGER.error("unsupported report format, keep original only: %s", path)
                target.unlink(missing_ok=True)
                return None
            self.last_outcome = "completed"
            LOGGER.info("pdf ready: %s -> %s", path, target)
            return target
        except Exception as exc:
            self.last_error = str(exc)[:1000] or exc.__class__.__name__
            self.last_outcome = "failed"
            target.unlink(missing_ok=True)
            LOGGER.exception("pdf conversion failed: %s", path)
            return None

    def ignore_reason(self, source: str | Path) -> str:
        path = Path(source)
        if path.is_file() and ACL_FIRMWARE_MARKER in self._probe(path).upper():
            return "HP ACL firmware/initialization stream"
        return ""

    def _target_path(self, source: Path, source_type: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in source.stem)[:70]
        return self.output_dir / f"{stamp}_{source_type}_{safe}.pdf"

    def _is_pdf(self, path: Path) -> bool:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"

    def _is_postscript(self, path: Path) -> bool:
        with path.open("rb") as handle:
            head = handle.read(8192)
        return head.startswith(b"%!") or b"%!PS" in head

    def _is_pcl(self, path: Path) -> bool:
        with path.open("rb") as handle:
            head = handle.read(65536)
        language = declared_pjl_language(head)
        return (
            language in {"PCL", "PCL5", "PCL5E", "PCL5C", "PCL6", "PCLXL"}
            or b"\x1bE" in head
            or b" HP-PCL XL;" in head
            or b"\x1b*t" in head
            or b"\x1b*b" in head
        )

    def _probe(self, path: Path) -> bytes:
        with path.open("rb") as handle:
            return handle.read(PRIVATE_RASTER_PROBE_BYTES)

    def _private_raster_to_pdf(
        self,
        source: Path,
        target: Path,
        spec: PrivateRasterSpec,
    ) -> bool:
        if not spec.enabled:
            self.last_error = spec.disabled_reason or f"{spec.label} decoder is disabled"
            LOGGER.warning("%s", self.last_error)
            return False
        command = self.config.zjsdecode if spec.protocol == "zjstream" else spec.decoder
        decoder = shutil.which(command)
        if not decoder:
            self.last_error = f"{command} is not installed"
            LOGGER.warning("%s is not installed; cannot convert %s", command, source)
            return False

        probe = self._probe(source)
        output_dpi = private_raster_dpi(probe, spec.protocol) or (600, 600)
        page_transform = private_raster_transform(probe, spec.protocol)
        with tempfile.TemporaryDirectory(prefix=f"jvlei-{spec.protocol}-") as directory:
            work = Path(directory)
            stream = work / f"stream.{spec.protocol}"
            page_prefix = work / "page"
            with source.open("rb") as source_handle, stream.open("wb") as stream_handle:
                if spec.payload_marker:
                    marker_offset = self._probe(source).find(spec.payload_marker)
                    if marker_offset < 0:
                        self.last_error = f"{spec.label} payload marker is missing"
                        return False
                    source_handle.seek(marker_offset)
                shutil.copyfileobj(source_handle, stream_handle)

            if spec.invocation == "input_prefix":
                result = subprocess.run(
                    [decoder, str(stream), str(page_prefix)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=PRIVATE_RASTER_TIMEOUT_SECONDS,
                )
            else:
                with stream.open("rb") as stream_handle:
                    result = subprocess.run(
                        [decoder, "-d", str(page_prefix)],
                        stdin=stream_handle,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=PRIVATE_RASTER_TIMEOUT_SECONDS,
                    )
            if result.returncode != 0:
                detail = result.stderr[-800:].strip()
                self.last_error = f"{command} failed with exit code {result.returncode}"
                if detail:
                    self.last_error += f": {detail}"
                LOGGER.warning("%s", self.last_error)
                return False
            return self._decoded_planes_to_pdf(
                work,
                target,
                command,
                spec,
                output_dpi,
                page_transform,
            )

    def _decoded_planes_to_pdf(
        self,
        work: Path,
        target: Path,
        command: str,
        spec: PrivateRasterSpec,
        output_dpi: tuple[int, int] = (600, 600),
        page_transform: str = "none",
    ) -> bool:
        grouped: dict[int, dict[tuple[int | None, int | None], Path]] = {}
        decoded_bytes = 0
        for path in sorted(work.glob("page-*.*")):
            match = PRIVATE_PAGE_PATTERN.fullmatch(path.name)
            if not match:
                continue
            decoded_bytes += path.stat().st_size
            if decoded_bytes > MAX_PRIVATE_RASTER_OUTPUT_BYTES:
                self.last_error = f"{command} output exceeds the 512 MB limit"
                return False
            page_number = int(match.group(1))
            plane_number = int(match.group(2)) if match.group(2) is not None else None
            subplane_number = int(match.group(3)) if match.group(3) is not None else None
            planes = grouped.setdefault(page_number, {})
            key = (plane_number, subplane_number)
            if key in planes:
                self.last_error = (
                    f"{command} produced duplicate page {page_number} "
                    f"plane {plane_number} subplane {subplane_number}"
                )
                return False
            planes[key] = path

        if not grouped or len(grouped) > MAX_PRIVATE_RASTER_PAGES:
            self.last_error = f"{command} produced an invalid page count: {len(grouped)}"
            return False

        pdf_dpi = (
            min(output_dpi[0], MAX_PRIVATE_RASTER_OUTPUT_DPI),
            min(output_dpi[1], MAX_PRIVATE_RASTER_OUTPUT_DPI),
        )
        pages: list[Image.Image] = []
        try:
            for page_number in sorted(grouped):
                page = self._compose_private_page(
                    grouped[page_number],
                    page_number,
                    command,
                    spec,
                    output_dpi,
                    pdf_dpi,
                )
                if page is None:
                    return False
                page = self._apply_private_page_transform(page, page_transform)
                pages.append(page)
            pages[0].save(
                target,
                "PDF",
                dpi=pdf_dpi,
                save_all=True,
                append_images=pages[1:],
            )
        finally:
            for page in pages:
                page.close()
        return target.is_file() and target.stat().st_size > 0

    @staticmethod
    def _apply_private_page_transform(image: Image.Image, transform: str) -> Image.Image:
        if transform == "mirror_horizontal":
            transformed = ImageOps.mirror(image)
        elif transform == "rotate_90":
            transformed = image.transpose(Image.Transpose.ROTATE_90)
        else:
            return image
        image.close()
        return transformed

    def _compose_private_page(
        self,
        plane_paths: dict[tuple[int | None, int | None], Path],
        page_number: int,
        command: str,
        spec: PrivateRasterSpec,
        source_dpi: tuple[int, int] = (600, 600),
        target_dpi: tuple[int, int] = (600, 600),
    ) -> Image.Image | None:
        loaded: dict[int, Image.Image] = {}
        generated: list[Image.Image] = []
        size: tuple[int, int] | None = None
        try:
            direct_paths = [path for (plane, _), path in plane_paths.items() if plane is None]
            if direct_paths:
                if len(direct_paths) != 1 or len(plane_paths) != 1:
                    self.last_error = f"{command} page {page_number} mixes page and plane images"
                    return None
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                    with Image.open(direct_paths[0]) as image:
                        return self._prepare_private_image(
                            image,
                            page_number,
                            command,
                            source_dpi,
                            target_dpi,
                            "RGB",
                        )

            grouped_planes: dict[int, dict[int, Path]] = {}
            for (plane_number, subplane_number), path in plane_paths.items():
                if plane_number is None:
                    continue
                subplane = 0 if subplane_number is None else subplane_number
                subplanes = grouped_planes.setdefault(plane_number, {})
                if subplane in subplanes:
                    self.last_error = (
                        f"{command} page {page_number} has duplicate subplane {subplane}"
                    )
                    return None
                subplanes[subplane] = path

            for plane_number, subplanes in grouped_planes.items():
                plane = self._load_private_plane(
                    subplanes,
                    page_number,
                    plane_number,
                    command,
                    spec,
                    generated,
                    source_dpi,
                    target_dpi,
                )
                if plane is None:
                    return None
                if size is None:
                    size = plane.size
                elif plane.size != size:
                    self.last_error = f"{command} page {page_number} has mismatched planes"
                    plane.close()
                    return None
                loaded[plane_number] = plane

            if not loaded or size is None:
                self.last_error = f"{command} page {page_number} has no readable planes"
                return None
            if len(loaded) == 1:
                plane_number = next(iter(loaded))
                if plane_number not in dict(spec.plane_channels):
                    self.last_error = (
                        f"{command} page {page_number} has unsupported plane {plane_number}"
                    )
                    return None
                return next(iter(loaded.values())).convert("RGB")

            channels: dict[str, Image.Image] = {}
            plane_channels = dict(spec.plane_channels)
            for plane_number, image in loaded.items():
                channel = plane_channels.get(plane_number)
                if channel is None or channel in channels:
                    self.last_error = f"{command} page {page_number} has unsupported plane {plane_number}"
                    return None
                channels[channel] = ImageOps.invert(image)
                generated.append(channels[channel])
            empty = Image.new("L", size, 0)
            generated.append(empty)
            cmyk = Image.merge(
                "CMYK",
                tuple(channels.get(name, empty) for name in ("C", "M", "Y", "K")),
            )
            generated.append(cmyk)
            return cmyk.convert("RGB")
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            self.last_error = f"{command} page {page_number} cannot be decoded: {exc}"
            return None
        finally:
            for image in loaded.values():
                image.close()
            for image in generated:
                image.close()

    def _load_private_plane(
        self,
        subplanes: dict[int, Path],
        page_number: int,
        plane_number: int,
        command: str,
        spec: PrivateRasterSpec,
        generated: list[Image.Image],
        source_dpi: tuple[int, int] = (600, 600),
        target_dpi: tuple[int, int] = (600, 600),
    ) -> Image.Image | None:
        images: dict[int, Image.Image] = {}
        try:
            for subplane_number, path in subplanes.items():
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                    with Image.open(path) as image:
                        converted = self._prepare_private_image(
                            image,
                            page_number,
                            command,
                            source_dpi,
                            target_dpi,
                            "L",
                        )
                        if converted is None:
                            return None
                if images and converted.size != next(iter(images.values())).size:
                    converted.close()
                    self.last_error = (
                        f"{command} page {page_number} plane {plane_number} "
                        "has mismatched subplanes"
                    )
                    return None
                images[subplane_number] = converted

            if len(images) == 1:
                return next(iter(images.values())).copy()
            if spec.subplane_mode != "oak_2bit" or set(images) != {0, 1}:
                self.last_error = (
                    f"{command} page {page_number} plane {plane_number} "
                    f"has unsupported subplanes {sorted(images)}"
                )
                return None

            low = ImageOps.invert(images[0])
            high = ImageOps.invert(images[1])
            black = ImageChops.subtract(high, low)
            dark = ImageChops.multiply(high, low).point(lambda value: value * 7 // 10)
            light = ImageChops.subtract(low, high).point(lambda value: value * 4 // 10)
            combined = ImageChops.add(black, dark)
            ink = ImageChops.add(combined, light)
            generated.extend((low, high, black, dark, light, combined, ink))
            return ImageOps.invert(ink)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            self.last_error = (
                f"{command} page {page_number} plane {plane_number} cannot be decoded: {exc}"
            )
            return None
        finally:
            for image in images.values():
                image.close()

    def _prepare_private_image(
        self,
        image: Image.Image,
        page_number: int,
        command: str,
        source_dpi: tuple[int, int],
        target_dpi: tuple[int, int],
        target_mode: str,
    ) -> Image.Image | None:
        source_pixels = image.width * image.height
        if source_pixels > MAX_PRIVATE_RASTER_SOURCE_PIXELS:
            self.last_error = (
                f"{command} page {page_number} exceeds the source pixel limit: "
                f"{image.size}"
            )
            return None
        if image.mode not in {"1", "L"} and source_pixels > MAX_PRIVATE_RASTER_PAGE_PIXELS:
            self.last_error = (
                f"{command} page {page_number} has an oversized decoded color image: "
                f"{image.size}"
            )
            return None

        width = max(1, round(image.width * target_dpi[0] / source_dpi[0]))
        height = max(1, round(image.height * target_dpi[1] / source_dpi[1]))
        if width * height > MAX_PRIVATE_RASTER_PAGE_PIXELS:
            self.last_error = (
                f"{command} page {page_number} exceeds the output pixel limit: "
                f"{width}x{height}"
            )
            return None

        image.load()
        if (width, height) == image.size:
            return image.convert(target_mode)
        resized = image.resize((width, height), Image.Resampling.BOX)
        try:
            return resized.convert(target_mode)
        finally:
            resized.close()

    def _pcl_to_pdf(self, source: Path, target: Path, label: str = "PCL/PCL XL") -> bool:
        for command in self.config.ghostpcl:
            binary = shutil.which(command)
            if not binary:
                continue
            result = subprocess.run(
                [
                    binary,
                    "-dNOPAUSE",
                    "-dBATCH",
                    "-sDEVICE=pdfwrite",
                    "-sPAPERSIZE=a4",
                    f"-sOutputFile={target}",
                    str(source),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=DOCUMENT_CONVERSION_TIMEOUT_SECONDS,
            )
            if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
                return True
            LOGGER.warning("GhostPCL failed command=%s stderr=%s", command, result.stderr[-1000:])
        self.last_error = f"GhostPCL is unavailable or could not convert {label}"
        return False

    def _xps_to_pdf(self, source: Path, target: Path) -> bool:
        for command in self.config.xps_converters:
            binary = shutil.which(command)
            if not binary:
                continue
            if Path(command).name == "xpstopdf":
                arguments = [binary, str(source), str(target)]
            else:
                arguments = [
                    binary,
                    "-dNOPAUSE",
                    "-dBATCH",
                    "-sDEVICE=pdfwrite",
                    f"-sOutputFile={target}",
                    str(source),
                ]
            result = subprocess.run(
                arguments,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=DOCUMENT_CONVERSION_TIMEOUT_SECONDS,
            )
            if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
                return True
            LOGGER.warning("XPS conversion failed command=%s stderr=%s", command, result.stderr[-1000:])
        self.last_error = "XPS converter is unavailable or could not convert XPS/OXPS"
        return False

    def _driverless_raster_to_pdf(
        self, source: Path, target: Path, label: str
    ) -> bool:
        """Convert CUPS/PWG Raster or Apple URF through the fixed CUPS filter."""

        binary = shutil.which(PWG_TO_PDF)
        if not binary:
            self.last_error = f"pwgtopdf is not installed for {label}"
            return False
        try:
            with target.open("wb") as output:
                result = subprocess.run(
                    [
                        binary,
                        "1",
                        "jvlei",
                        "PRN conversion",
                        "1",
                        "",
                        str(source),
                    ],
                    stdout=output,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=DOCUMENT_CONVERSION_TIMEOUT_SECONDS,
                )
        except OSError as exc:
            self.last_error = f"pwgtopdf could not be started: {exc}"
            return False
        if (
            result.returncode == 0
            and target.exists()
            and target.stat().st_size > 5
            and self._is_pdf(target)
        ):
            return True
        detail = result.stderr[-800:].strip()
        self.last_error = f"pwgtopdf could not convert {label}"
        if detail:
            self.last_error += f": {detail}"
        LOGGER.warning("%s", self.last_error)
        return False

    def _escp_to_pdf(
        self, source: Path, target: Path, protocol: str, probe: bytes
    ) -> bool:
        for command in self.config.escp_converters:
            binary = shutil.which(command)
            if not binary:
                continue
            with tempfile.TemporaryDirectory(prefix="jvlei-escp-") as directory:
                working_dir = Path(directory)
                convert_source = self._prepare_escapy_source(source, working_dir)
                arguments = [binary]
                if protocol == "escp":
                    arguments.extend(["--pins", str(self.config.escp_pins)])
                else:
                    profile = self.config.escp2_profile
                    if profile == "auto":
                        profile, evidence = detect_escp2_profile_hint(probe)
                        if profile is None:
                            self.last_error = (
                                "ESC/P2严格自动匹配失败："
                                f"{evidence}；已保留原始PRN"
                            )
                            self.last_outcome = "retained"
                            return False
                        LOGGER.info("ESC/P2 auto-selected profile=%s: %s", profile, evidence)
                    self.last_escp2_profile = profile
                    profile_config = (
                        ESCAPY_PROFILE_CONFIG_ROOT
                        / profile
                        / "escapy.conf"
                    )
                    if profile_config.is_file():
                        arguments.extend(["--config", str(profile_config)])
                    elif profile != "generic":
                        self.last_error = (
                            "EscaPy profile is not installed: "
                            f"{profile}"
                        )
                        return False
                arguments.extend(["-o", str(target), str(convert_source)])
                result = subprocess.run(
                    arguments,
                    cwd=working_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=DOCUMENT_CONVERSION_TIMEOUT_SECONDS,
                )
            if (
                result.returncode == 0
                and target.exists()
                and target.stat().st_size > 5
                and self._is_pdf(target)
            ):
                return True
            LOGGER.warning(
                "ESC/P conversion failed command=%s stderr=%s",
                command,
                result.stderr[-1000:],
            )
        self.last_error = "EscaPy is unavailable or could not convert ESC/P or ESC/P2"
        return False

    def _escpr_to_pdf(self, source: Path, target: Path) -> bool:
        try:
            document = decode_escpr(source)
        except (OSError, EscprDecodeError) as exc:
            self.last_error = f"ESC/P-R could not be decoded: {exc}"
            LOGGER.warning("%s", self.last_error)
            return False
        try:
            document.pages[0].save(
                target,
                "PDF",
                dpi=(document.dpi, document.dpi),
                save_all=True,
                append_images=document.pages[1:],
            )
        except (OSError, ValueError) as exc:
            self.last_error = f"ESC/P-R PDF creation failed: {exc}"
            return False
        finally:
            document.close()
        return target.is_file() and target.stat().st_size > 5 and self._is_pdf(target)

    @staticmethod
    def _prepare_escapy_source(source: Path, working_dir: Path) -> Path:
        """Remove only the final job-eject FF that makes EscaPy add a blank page."""
        size = source.stat().st_size
        if size == 0:
            return source
        probe_size = min(size, ESCP_TRAILER_PROBE_BYTES)
        with source.open("rb") as handle:
            handle.seek(size - probe_size)
            trailer = handle.read(probe_size)
        form_feed_index = next(
            (
                offset
                for offset in range(len(trailer) - 1, -1, -1)
                if trailer[offset] == 0x0C
                and PdfConverter._is_escp_job_trailer(trailer[offset + 1 :])
            ),
            None,
        )
        if form_feed_index is None:
            return source

        form_feed_offset = size - probe_size + form_feed_index
        prepared = working_dir / f"{source.stem}-escapy{source.suffix or '.prn'}"
        with source.open("rb") as input_handle, prepared.open("wb") as output_handle:
            remaining = form_feed_offset
            while remaining:
                chunk = input_handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise OSError("ESC/P source ended before its terminal form feed")
                output_handle.write(chunk)
                remaining -= len(chunk)
            if input_handle.read(1) != b"\x0c":
                raise OSError("ESC/P terminal form feed changed while preparing input")
            shutil.copyfileobj(input_handle, output_handle)
        return prepared

    @staticmethod
    def _is_escp_job_trailer(trailer: bytes) -> bool:
        position = 0
        while position < len(trailer):
            if trailer[position] in b" \t\r\n":
                position += 1
                continue
            if trailer.startswith(ESCP_RESET, position):
                position += len(ESCP_RESET)
                continue
            if trailer.startswith(ESCP_UEL, position):
                position += len(ESCP_UEL)
                continue
            if trailer.startswith(ESCP_REMOTE_PREFIX, position):
                position = PdfConverter._consume_escp_remote_trailer(
                    trailer, position + len(ESCP_REMOTE_PREFIX)
                )
                if position < 0:
                    return False
                continue
            return False
        return True

    @staticmethod
    def _consume_escp_remote_trailer(trailer: bytes, position: int) -> int:
        seen: set[bytes] = set()
        while position < len(trailer):
            if trailer.startswith(b"\x1b\x00\x00\x00", position):
                return position + 4
            if trailer.startswith(b"\x1b\x00", position):
                return position + 2
            if position + 4 > len(trailer):
                return -1
            command = trailer[position : position + 2]
            expected = ESCP_REMOTE_COMMANDS.get(command)
            if expected is None or command in seen:
                return -1
            payload_size = int.from_bytes(trailer[position + 2 : position + 4], "little")
            expected_size, expected_payload = expected
            payload_start = position + 4
            payload_end = payload_start + payload_size
            if (
                payload_size != expected_size
                or payload_end > len(trailer)
                or trailer[payload_start:payload_end] != expected_payload
            ):
                return -1
            seen.add(command)
            position = payload_end
        return -1

    def _ps_to_pdf(self, source: Path, target: Path) -> bool:
        binary = shutil.which(self.config.ps2pdf)
        if not binary:
            return False
        convert_source = source
        temp_path: Path | None = None
        head = source.read_bytes()[:8192]
        marker = head.find(b"%!PS")
        try:
            if marker > 0:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".ps") as temp:
                    temp_path = Path(temp.name)
                    with source.open("rb") as handle:
                        handle.seek(marker)
                        shutil.copyfileobj(handle, temp)
                convert_source = temp_path
            result = subprocess.run(
                [binary, str(convert_source), str(target)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=DOCUMENT_CONVERSION_TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                LOGGER.warning("ps2pdf failed: %s", result.stderr[-1000:])
                self.last_error = "Ghostscript could not convert PostScript"
                return False
            return target.exists()
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    def _image_to_pdf(self, source: Path, target: Path, label: str = "image") -> bool:
        pages: list[Image.Image] = []
        try:
            with Image.open(source) as image:
                frame_count = int(getattr(image, "n_frames", 1))
                if frame_count < 1 or frame_count > MAX_IMAGE_PAGES:
                    self.last_error = f"{label} has an invalid page count: {frame_count}"
                    return False
                total_pixels = 0
                for frame_number in range(frame_count):
                    image.seek(frame_number)
                    image.load()
                    pixels = image.width * image.height
                    total_pixels += pixels
                    if pixels > MAX_IMAGE_PAGE_PIXELS:
                        self.last_error = (
                            f"{label} page {frame_number + 1} exceeds the pixel limit: "
                            f"{image.size}"
                        )
                        return False
                    if total_pixels > MAX_IMAGE_TOTAL_PIXELS:
                        self.last_error = f"{label} exceeds the total pixel limit"
                        return False
                    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                        rgba = image.convert("RGBA")
                        background = Image.new("RGB", image.size, "white")
                        background.paste(rgba, mask=rgba.getchannel("A"))
                        rgba.close()
                        pages.append(background)
                    else:
                        pages.append(image.convert("RGB"))
            pages[0].save(
                target,
                "PDF",
                resolution=100.0,
                save_all=True,
                append_images=pages[1:],
            )
            return target.is_file() and target.stat().st_size > 0
        except (OSError, ValueError, EOFError) as exc:
            self.last_error = f"{label} could not be converted: {exc}"
            return False
        finally:
            for page in pages:
                page.close()

    def _text_to_pdf(self, source: Path, target: Path) -> bool:
        head = source.read_bytes()[:8192]
        if b"\x00" in head:
            return False
        control_count = sum(byte < 9 or 13 < byte < 32 for byte in head)
        if head and control_count / len(head) > 0.02:
            return False
        text = None
        for encoding in ("utf-8", "gb18030"):
            try:
                text = source.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return False
        pages = self._text_pages(text)
        pages[0].save(target, "PDF", save_all=True, append_images=pages[1:])
        return True

    def _text_pages(self, text: str) -> list[Image.Image]:
        font = self._font(24)
        small = self._font(18)
        lines: list[str] = []
        for raw in text.splitlines() or [""]:
            while len(raw) > 36:
                lines.append(raw[:36])
                raw = raw[36:]
            lines.append(raw)
        pages: list[Image.Image] = []
        for offset in range(0, len(lines), 26):
            image = Image.new("RGB", (1240, 1754), "white")
            draw = ImageDraw.Draw(image)
            y = 70
            for line in lines[offset : offset + 26]:
                draw.text((70, y), line, font=font, fill="black")
                y += 58
            draw.text((70, 1680), "Gadget MSC Printer", font=small, fill="#666666")
            pages.append(image)
        return pages or [Image.new("RGB", (1240, 1754), "white")]

    def _font(self, size: int):
        for path in (
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()
