from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import PdfConfig

LOGGER = logging.getLogger(__name__)
ZJSTREAM_MAGIC = b"JZJZ"
ACL_FIRMWARE_MARKER = b"AGIACLDOWNLOAD"
ZJSTREAM_PROBE_BYTES = 1024 * 1024
MAX_ZJSTREAM_PAGES = 100
MAX_ZJSTREAM_PAGE_PIXELS = 200_000_000


class PdfConverter:
    def __init__(self, config: PdfConfig) -> None:
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def convert(self, source: str | Path, source_type: str) -> Path | None:
        if not self.config.enabled:
            return None
        path = Path(source)
        if not path.is_file():
            LOGGER.warning("source missing: %s", path)
            return None
        ignored = self.ignore_reason(path)
        if ignored:
            LOGGER.info("ignore non-report print stream: %s reason=%s", path, ignored)
            return None
        target = self._target_path(path, source_type)
        try:
            if self._is_pdf(path):
                # FAT timestamps are local-time values and can appear hours in the
                # future on a UTC board. The generated report must use board time.
                shutil.copyfile(path, target)
            elif self._is_zjstream(path):
                if not self._zjstream_to_pdf(path, target):
                    target.unlink(missing_ok=True)
                    return None
            elif self._is_pcl(path) and self._pcl_to_pdf(path, target):
                pass
            elif self._is_postscript(path) and self._ps_to_pdf(path, target):
                pass
            elif self._image_to_pdf(path, target):
                pass
            elif self._text_to_pdf(path, target):
                pass
            else:
                LOGGER.error("unsupported report format, keep original only: %s", path)
                target.unlink(missing_ok=True)
                return None
            LOGGER.info("pdf ready: %s -> %s", path, target)
            return target
        except Exception:
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
        return path.read_bytes()[:5] == b"%PDF-"

    def _is_postscript(self, path: Path) -> bool:
        head = path.read_bytes()[:8192]
        return head.startswith(b"%!") or b"%!PS" in head

    def _is_pcl(self, path: Path) -> bool:
        head = path.read_bytes()[:65536]
        return (
            b"\x1bE" in head
            or b"%-12345X" in head
            or b"@PJL" in head
            or b" HP-PCL XL;" in head
            or b"\x1b*t" in head
            or b"\x1b*b" in head
        )

    def _is_zjstream(self, path: Path) -> bool:
        return ZJSTREAM_MAGIC in self._probe(path)

    def _probe(self, path: Path) -> bytes:
        with path.open("rb") as handle:
            return handle.read(ZJSTREAM_PROBE_BYTES)

    def _zjstream_to_pdf(self, source: Path, target: Path) -> bool:
        decoder = shutil.which(self.config.zjsdecode)
        if not decoder:
            LOGGER.warning("zjsdecode is not installed; cannot convert %s", source)
            return False
        marker_offset = self._probe(source).find(ZJSTREAM_MAGIC)
        if marker_offset < 0:
            return False

        with tempfile.TemporaryDirectory(prefix="jvlei-zjs-") as directory:
            work = Path(directory)
            stream = work / "stream.zjs"
            page_prefix = work / "page"
            with source.open("rb") as source_handle, stream.open("wb") as stream_handle:
                source_handle.seek(marker_offset)
                shutil.copyfileobj(source_handle, stream_handle)

            with stream.open("rb") as stream_handle:
                result = subprocess.run(
                    [decoder, "-d", str(page_prefix)],
                    stdin=stream_handle,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=120,
                )
            if result.returncode != 0:
                LOGGER.warning("zjsdecode failed: %s", result.stderr[-1000:])
                return False

            page_paths = sorted(work.glob("page-*-*.pbm"))
            if not page_paths or len(page_paths) > MAX_ZJSTREAM_PAGES:
                LOGGER.warning("zjsdecode produced an invalid page count: %d", len(page_paths))
                return False

            pages: list[Image.Image] = []
            page_numbers: set[str] = set()
            try:
                for page_path in page_paths:
                    parts = page_path.stem.rsplit("-", 2)
                    page_number = parts[-2] if len(parts) == 3 else page_path.stem
                    if page_number in page_numbers:
                        LOGGER.warning("multi-plane color ZjStream is not supported: %s", source)
                        return False
                    page_numbers.add(page_number)
                    with Image.open(page_path) as image:
                        if image.width * image.height > MAX_ZJSTREAM_PAGE_PIXELS:
                            LOGGER.warning("ZjStream page dimensions are too large: %s", image.size)
                            return False
                        pages.append(image.copy())
                pages[0].save(
                    target,
                    "PDF",
                    resolution=600.0,
                    save_all=True,
                    append_images=pages[1:],
                )
            finally:
                for page in pages:
                    page.close()
            return target.is_file() and target.stat().st_size > 0

    def _pcl_to_pdf(self, source: Path, target: Path) -> bool:
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
            )
            if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
                return True
            LOGGER.warning("GhostPCL failed command=%s stderr=%s", command, result.stderr[-1000:])
        return False

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
            result = subprocess.run([binary, str(convert_source), str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                LOGGER.warning("ps2pdf failed: %s", result.stderr[-1000:])
                return False
            return target.exists()
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    def _image_to_pdf(self, source: Path, target: Path) -> bool:
        try:
            with Image.open(source) as image:
                if image.mode in ("RGBA", "LA"):
                    background = Image.new("RGB", image.size, "white")
                    background.paste(image, mask=image.getchannel("A"))
                    image = background
                else:
                    image = image.convert("RGB")
                image.save(target, "PDF", resolution=100.0)
            return True
        except Exception:
            return False

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
