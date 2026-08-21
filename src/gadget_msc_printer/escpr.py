from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

ESCPR_MODE = b"\x1b(R\x06\x00\x00ESCPR"
ESCPR_QUALITY_COMMAND = b"\x1bq\x09\x00\x00\x00setq"

MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_COMMAND_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_PAGES = 100
MAX_PAGE_PIXELS = 75_000_000
MAX_TOTAL_PIXELS = 100_000_000
MAX_DECODED_BYTES = 512 * 1024 * 1024
MAX_COMMANDS = 2_000_000
MAX_RASTERS_PER_PAGE_FACTOR = 4

_DPI_BY_CODE = {
    0: 360,
    1: 720,
    2: 300,
    3: 600,
}


class EscprDecodeError(ValueError):
    pass


@dataclass
class EscprDocument:
    pages: list[Image.Image]
    dpi: int

    def close(self) -> None:
        for page in self.pages:
            page.close()


@dataclass(frozen=True)
class _PageGeometry:
    width: int
    height: int
    top_margin: int
    left_margin: int
    printable_width: int
    printable_height: int
    dpi: int


def decode_escpr(source: str | Path) -> EscprDocument:
    """Decode Epson ESC/P-R RGB raster jobs emitted by printer-driver-escpr."""

    path = Path(source)
    source_size = path.stat().st_size
    if source_size <= 0 or source_size > MAX_SOURCE_BYTES:
        raise EscprDecodeError("ESC/P-R source size is outside the 256 MB limit")
    data = path.read_bytes()
    if ESCPR_MODE not in data[:1024 * 1024]:
        raise EscprDecodeError("ESC/P-R mode signature is missing")

    position = data.find(ESCPR_QUALITY_COMMAND)
    if position < 0:
        raise EscprDecodeError("ESC/P-R setq command is missing")

    pages: list[Image.Image] = []
    current_page: Image.Image | None = None
    current_geometry: _PageGeometry | None = None
    job_geometry: _PageGeometry | None = None
    bytes_per_pixel: int | None = None
    document_dpi: int | None = None
    decoded_bytes = 0
    total_pixels = 0
    raster_count = 0
    command_count = 0
    saw_end_job = False

    try:
        while position + 10 <= len(data):
            command_count += 1
            if command_count > MAX_COMMANDS:
                raise EscprDecodeError("ESC/P-R command count exceeds the safety limit")
            if data[position] != 0x1B:
                raise EscprDecodeError(f"invalid ESC/P-R command at offset {position}")

            parameter_size = int.from_bytes(data[position + 2 : position + 6], "little")
            if parameter_size > MAX_COMMAND_PAYLOAD_BYTES:
                raise EscprDecodeError("ESC/P-R command payload exceeds the 16 MB limit")
            name_bytes = data[position + 6 : position + 10]
            if len(name_bytes) != 4 or not all(0x20 <= value <= 0x7E for value in name_bytes):
                raise EscprDecodeError(f"invalid ESC/P-R command name at offset {position}")
            payload_start = position + 10
            payload_end = payload_start + parameter_size
            if payload_end > len(data):
                raise EscprDecodeError("truncated ESC/P-R command payload")
            payload = data[payload_start:payload_end]
            name = name_bytes.decode("ascii")

            if name == "setq":
                bytes_per_pixel = _parse_quality(payload)
            elif name == "setj":
                job_geometry = _parse_job_geometry(payload)
            elif name == "sttp":
                if payload:
                    raise EscprDecodeError("invalid ESC/P-R start-page payload")
                if current_page is not None:
                    raise EscprDecodeError("nested ESC/P-R pages are not allowed")
                if bytes_per_pixel is None or job_geometry is None:
                    raise EscprDecodeError("ESC/P-R page starts before job setup")
                if len(pages) >= MAX_PAGES:
                    raise EscprDecodeError("ESC/P-R page count exceeds the 100-page limit")
                total_pixels += job_geometry.width * job_geometry.height
                if total_pixels > MAX_TOTAL_PIXELS:
                    raise EscprDecodeError("ESC/P-R document exceeds the 100-megapixel limit")
                if document_dpi is None:
                    document_dpi = job_geometry.dpi
                elif document_dpi != job_geometry.dpi:
                    raise EscprDecodeError("mixed ESC/P-R page resolutions are not supported")
                current_geometry = job_geometry
                current_page = Image.new(
                    "RGB",
                    (current_geometry.width, current_geometry.height),
                    "white",
                )
                raster_count = 0
            elif name == "dsnd":
                if current_page is None or current_geometry is None or bytes_per_pixel is None:
                    raise EscprDecodeError("ESC/P-R raster data appears outside a page")
                raster_count += 1
                if raster_count > current_geometry.height * MAX_RASTERS_PER_PAGE_FACTOR:
                    raise EscprDecodeError("ESC/P-R raster count exceeds the page safety limit")
                x, y, raster = _decode_raster(payload, bytes_per_pixel)
                decoded_bytes += len(raster)
                if decoded_bytes > MAX_DECODED_BYTES:
                    raise EscprDecodeError("ESC/P-R decoded raster exceeds the 512 MB limit")
                width = len(raster) // bytes_per_pixel
                page_x = current_geometry.left_margin + x
                page_y = current_geometry.top_margin + y
                if (
                    width <= 0
                    or x + width > current_geometry.printable_width
                    or y >= current_geometry.printable_height
                    or page_x + width > current_geometry.width
                    or page_y >= current_geometry.height
                ):
                    raise EscprDecodeError("ESC/P-R raster coordinates exceed the page")
                if bytes_per_pixel != 3:
                    raise EscprDecodeError("only RGB ESC/P-R raster pages are supported")
                strip = Image.frombytes("RGB", (width, 1), raster)
                try:
                    current_page.paste(strip, (page_x, page_y))
                finally:
                    strip.close()
            elif name == "endp":
                if len(payload) != 1:
                    raise EscprDecodeError("invalid ESC/P-R end-page payload")
                if current_page is None:
                    raise EscprDecodeError("ESC/P-R end-page appears without a page")
                pages.append(current_page)
                current_page = None
                current_geometry = None
            elif name == "endj":
                if payload:
                    raise EscprDecodeError("invalid ESC/P-R end-job payload")
                if current_page is not None:
                    raise EscprDecodeError("ESC/P-R job ended before its page")
                saw_end_job = True
                break

            position = payload_end

        if not saw_end_job:
            raise EscprDecodeError("ESC/P-R end-job command is missing")
        if not pages or document_dpi is None:
            raise EscprDecodeError("ESC/P-R job contains no complete pages")
        return EscprDocument(pages=pages, dpi=document_dpi)
    except Exception:
        if current_page is not None:
            current_page.close()
        for page in pages:
            page.close()
        raise


def _parse_quality(payload: bytes) -> int:
    if len(payload) < 9:
        raise EscprDecodeError("invalid ESC/P-R setq payload")
    color_plane = payload[6]
    palette_size = int.from_bytes(payload[7:9], "big")
    if len(payload) != 9 + palette_size:
        raise EscprDecodeError("ESC/P-R palette length does not match setq")
    if color_plane != 0:
        raise EscprDecodeError("only full-color RGB ESC/P-R jobs are supported")
    return 3


def _parse_job_geometry(payload: bytes) -> _PageGeometry:
    if len(payload) != 22:
        raise EscprDecodeError("invalid ESC/P-R setj payload")
    width = int.from_bytes(payload[0:4], "big")
    height = int.from_bytes(payload[4:8], "big")
    top_margin = int.from_bytes(payload[8:10], "big")
    left_margin = int.from_bytes(payload[10:12], "big")
    printable_width = int.from_bytes(payload[12:16], "big")
    printable_height = int.from_bytes(payload[16:20], "big")
    dpi = _DPI_BY_CODE.get(payload[20])
    if dpi is None:
        raise EscprDecodeError("unsupported ESC/P-R input resolution")
    if width <= 0 or height <= 0 or width * height > MAX_PAGE_PIXELS:
        raise EscprDecodeError("ESC/P-R page dimensions exceed the 75-megapixel limit")
    if (
        printable_width <= 0
        or printable_height <= 0
        or left_margin + printable_width > width
        or top_margin + printable_height > height
    ):
        raise EscprDecodeError("invalid ESC/P-R printable area")
    return _PageGeometry(
        width=width,
        height=height,
        top_margin=top_margin,
        left_margin=left_margin,
        printable_width=printable_width,
        printable_height=printable_height,
        dpi=dpi,
    )


def _decode_raster(payload: bytes, bytes_per_pixel: int) -> tuple[int, int, bytes]:
    if len(payload) < 7:
        raise EscprDecodeError("invalid ESC/P-R dsnd payload")
    x = int.from_bytes(payload[0:2], "big")
    y = int.from_bytes(payload[2:4], "big")
    compression = payload[4]
    encoded_size = int.from_bytes(payload[5:7], "big")
    encoded = payload[7:]
    if encoded_size != len(encoded):
        raise EscprDecodeError("ESC/P-R raster length does not match dsnd")
    if compression == 0:
        raster = encoded
    elif compression == 1:
        raster = _decode_pixel_rle(encoded, bytes_per_pixel)
    else:
        raise EscprDecodeError(f"unsupported ESC/P-R compression mode {compression}")
    if not raster or len(raster) % bytes_per_pixel:
        raise EscprDecodeError("invalid ESC/P-R raster pixel length")
    return x, y, raster


def _decode_pixel_rle(encoded: bytes, bytes_per_pixel: int) -> bytes:
    decoded = bytearray()
    position = 0
    while position < len(encoded):
        control = encoded[position]
        position += 1
        if control >= 0x80:
            count = 257 - control
            end = position + bytes_per_pixel
            if end > len(encoded):
                raise EscprDecodeError("truncated ESC/P-R repeated pixel")
            decoded.extend(encoded[position:end] * count)
            position = end
        else:
            count = control + 1
            end = position + count * bytes_per_pixel
            if end > len(encoded):
                raise EscprDecodeError("truncated ESC/P-R literal pixels")
            decoded.extend(encoded[position:end])
            position = end
        if len(decoded) > MAX_DECODED_BYTES:
            raise EscprDecodeError("ESC/P-R raster expansion exceeds the safety limit")
    return bytes(decoded)
