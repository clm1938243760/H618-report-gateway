from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PrivateRasterSpec:
    protocol: str
    label: str
    decoder: str
    evidence: str
    payload_marker: bytes = b""
    plane_channels: tuple[tuple[int, str], ...] = ((0, "K"), (4, "K"))
    subplane_mode: str = "single"
    invocation: str = "stdin_dash_d"
    enabled: bool = True
    disabled_reason: str = ""


PRIVATE_RASTER_SPECS = (
    PrivateRasterSpec(
        protocol="zjstream",
        label="ZjStream",
        decoder="zjsdecode",
        evidence="检测到 ZjStream JZJZ 魔数或 ACL 页面语言",
        payload_marker=b"JZJZ",
        plane_channels=((1, "C"), (2, "Y"), (3, "M"), (0, "K"), (4, "K")),
    ),
    PrivateRasterSpec(
        protocol="spl",
        label="Samsung QPDL/SPL-C",
        decoder="qpdldecode",
        evidence="检测到 Samsung QPDL/SPL-C 打印语言",
        plane_channels=((1, "C"), (2, "M"), (3, "Y"), (4, "K")),
    ),
    PrivateRasterSpec(
        protocol="xqx",
        label="HP XQX",
        decoder="xqxdecode",
        evidence="检测到 HP XQX 打印流标记",
        plane_channels=((4, "K"),),
    ),
    PrivateRasterSpec(
        protocol="hiperc",
        label="OKI HIPERC",
        decoder="hipercdecode",
        evidence="检测到 OKI HIPERC 打印语言",
        plane_channels=((0, "C"), (1, "M"), (2, "Y"), (3, "K")),
    ),
    PrivateRasterSpec(
        protocol="hbpl",
        label="HBPL",
        decoder="/usr/local/libexec/jvlei-prn-decoders/hbpldecode",
        evidence="检测到 HBPL 打印语言",
        plane_channels=((1, "C"), (2, "M"), (3, "Y"), (0, "K"), (4, "K")),
    ),
    PrivateRasterSpec(
        protocol="ddst",
        label="Ricoh DDST",
        decoder="/usr/local/libexec/jvlei-prn-decoders/ddstdecode",
        evidence="检测到 Ricoh DDST JBIG 页面控制命令",
        plane_channels=((4, "K"),),
    ),
    PrivateRasterSpec(
        protocol="lavaflow",
        label="LAVAFLOW",
        decoder="lavadecode",
        evidence="检测到 LAVAFLOW 打印语言",
        plane_channels=((1, "Y"), (2, "M"), (3, "C"), (4, "K")),
    ),
    PrivateRasterSpec(
        protocol="opl",
        label="Raster Object/OPL",
        decoder="/usr/local/libexec/jvlei-prn-decoders/opldecode",
        evidence="检测到 Raster Object/OPL 作业结构",
        plane_channels=((1, "C"), (2, "M"), (3, "Y"), (4, "K")),
    ),
    PrivateRasterSpec(
        protocol="slx",
        label="Lexmark SLX",
        decoder="/usr/local/libexec/jvlei-prn-decoders/slxdecode",
        evidence="检测到 Lexmark SLX 打印流魔数",
        plane_channels=((1, "K"), (2, "C"), (3, "M"), (4, "Y")),
    ),
    PrivateRasterSpec(
        protocol="oakt",
        label="Oak Technology OAKT",
        decoder="oakdecode",
        evidence="检测到 Oak Technology OAKT 记录",
        payload_marker=b"OAKT",
        plane_channels=((0, "Y"), (1, "M"), (2, "C"), (3, "K")),
        subplane_mode="oak_2bit",
    ),
    PrivateRasterSpec(
        protocol="gipd",
        label="Granite GIPD",
        decoder="gipddecode",
        evidence="检测到 Granite GIPD 作业和页面记录",
        plane_channels=((0, "K"), (1, "C"), (2, "M"), (3, "Y"), (4, "K")),
        enabled=False,
        disabled_reason=(
            "Ubuntu Noble gipddecode 对 GDIJ/GDIP/GDIB 只输出结构，"
            "不能导出页面；保留原始 PRN 等待专用解码器"
        ),
    ),
    PrivateRasterSpec(
        protocol="brother_hbp",
        label="Brother HBP/XL2HB",
        decoder="/usr/local/libexec/jvlei-prn-decoders/brdecode",
        evidence="检测到 Brother RAS1200MODE 和 1030 压缩栅格命令",
        plane_channels=((0, "K"),),
        invocation="input_prefix",
    ),
)

PRIVATE_RASTER_BY_PROTOCOL = {item.protocol: item for item in PRIVATE_RASTER_SPECS}
PJL_PRIVATE_PROTOCOLS = {
    b"ACL": "zjstream",
    b"ZJS": "zjstream",
    b"ZJSTREAM": "zjstream",
    b"QPDL": "spl",
    b"SPL": "spl",
    b"SPL-C": "spl",
    b"SPLC": "spl",
    b"XQX": "xqx",
    b"HIPERC": "hiperc",
    b"HBPL": "hbpl",
    b"HBPL2": "hbpl",
    b"DDST": "ddst",
    b"LAVAFLOW": "lavaflow",
    b"OPL": "opl",
    b"SLX": "slx",
    b"OAKT": "oakt",
    b"GIPD": "gipd",
    b"HBP": "brother_hbp",
    b"XL2HB": "brother_hbp",
}


def private_raster_spec(protocol: str) -> PrivateRasterSpec | None:
    return PRIVATE_RASTER_BY_PROTOCOL.get(protocol)


def private_protocol_from_pjl(language: bytes) -> str | None:
    return PJL_PRIVATE_PROTOCOLS.get(language.strip().upper())


def private_raster_dpi(data: bytes, protocol: str) -> tuple[int, int] | None:
    """Return the physical DPI represented by a decoder's PBM output."""

    if protocol == "spl":
        resolution = _qpdl_dpi(data)
        if resolution:
            return resolution
    elif protocol == "xqx":
        resolution = _xqx_dpi(data)
        if resolution:
            return resolution
    elif protocol == "hbpl":
        resolution = _hbpl_dpi(data)
        if resolution:
            return resolution
    elif protocol == "lavaflow":
        resolution = _lavaflow_dpi(data)
        if resolution:
            return resolution
    elif protocol == "opl":
        resolution = _opl_dpi(data)
        if resolution:
            return resolution
    elif protocol == "slx":
        resolution = _slx_dpi(data)
        if resolution:
            return resolution
    elif protocol == "oakt":
        resolution = _oakt_dpi(data)
        if resolution:
            return resolution
    return _pjl_dpi(data)


def private_raster_transform(data: bytes, protocol: str) -> str:
    if protocol == "oakt":
        _, transform = _oakt_page_metadata(data)
        return transform
    return "none"


def detect_private_raster(data: bytes) -> PrivateRasterSpec | None:
    if not data:
        return None
    upper = data.upper()
    if b"AGIACLDOWNLOAD" in upper:
        return None

    if b"JZJZ" in data or _declares_language(upper, (b"ACL", b"ZJS", b"ZJSTREAM")):
        return PRIVATE_RASTER_BY_PROTOCOL["zjstream"]
    if _declares_language(upper, (b"QPDL", b"SPL", b"SPL-C", b"SPLC")) or any(
        marker in upper for marker in (b"SPL-C", b"SPL2")
    ):
        return PRIVATE_RASTER_BY_PROTOCOL["spl"]
    if b",XQX" in data or _declares_language(upper, (b"XQX",)):
        return PRIVATE_RASTER_BY_PROTOCOL["xqx"]
    if _declares_language(upper, (b"HIPERC",)):
        return PRIVATE_RASTER_BY_PROTOCOL["hiperc"]
    if _declares_language(upper, (b"HBPL", b"HBPL2")) or (
        b"\x1bJP" in data and b"\x1bPS" in data
    ):
        return PRIVATE_RASTER_BY_PROTOCOL["hbpl"]
    if _declares_language(upper, (b"DDST",)) or all(
        marker in upper
        for marker in (b"@PJL SET COMPRESS=JBIG", b"PAGESTATUS=START", b"IMAGELEN=")
    ):
        return PRIVATE_RASTER_BY_PROTOCOL["ddst"]
    if _declares_language(upper, (b"LAVAFLOW",)):
        return PRIVATE_RASTER_BY_PROTOCOL["lavaflow"]
    if data.startswith(b"Event=StartOfJob;") and b"RasterObject." in data:
        return PRIVATE_RASTER_BY_PROTOCOL["opl"]
    if data.startswith(b"\xa5SLX") or b"\xa5SLX" in data[:256]:
        return PRIVATE_RASTER_BY_PROTOCOL["slx"]
    if data.startswith(b"OAKT") or b"OAKT" in data[:4096]:
        return PRIVATE_RASTER_BY_PROTOCOL["oakt"]
    if b"GDIJ" in data and b"GDIP" in data:
        return PRIVATE_RASTER_BY_PROTOCOL["gipd"]
    if _declares_language(upper, (b"HBP", b"XL2HB")) or (
        b"@PJL SET RAS1200MODE" in upper
        and re.search(rb"\x1b\*B1030M\d+W", upper) is not None
    ):
        return PRIVATE_RASTER_BY_PROTOCOL["brother_hbp"]
    return None


def _declares_language(data: bytes, names: tuple[bytes, ...]) -> bool:
    match = re.search(rb"ENTER\s+LANGUAGE\s*=\s*([A-Z0-9_-]+)", data)
    return bool(match and match.group(1) in names)


def _qpdl_dpi(data: bytes) -> tuple[int, int] | None:
    marker = re.search(
        rb"@PJL\s+ENTER\s+LANGUAGE\s*=\s*QPDL[^\r\n]*(?:\r\n|\r|\n)",
        data.upper(),
    )
    if not marker:
        return None
    offset = marker.end()
    if offset + 17 > len(data) or data[offset] != 0x00:
        return None
    page_header = data[offset + 1 : offset + 17]
    y_dpi = page_header[0] * 100
    x_dpi = (int.from_bytes(page_header[14:16], "big") & 0xFF) * 100
    return _validated_dpi(x_dpi, y_dpi)


def _xqx_dpi(data: bytes) -> tuple[int, int] | None:
    offset = data.find(b",XQX")
    if offset < 0:
        return None
    offset += 4
    values: dict[int, int] = {}
    for _ in range(64):
        if offset + 8 > len(data):
            return None
        record_type = int.from_bytes(data[offset : offset + 4], "big")
        item_count = int.from_bytes(data[offset + 4 : offset + 8], "big")
        offset += 8
        if item_count > 1024:
            return None
        if record_type == 7:  # XQX_JBIG stores a byte count, not typed items.
            offset += item_count
            continue
        for _ in range(item_count):
            if offset + 8 > len(data):
                return None
            item_type = int.from_bytes(data[offset : offset + 4], "big")
            item_size = int.from_bytes(data[offset + 4 : offset + 8], "big")
            offset += 8
            if item_size > len(data) - offset:
                return None
            if item_size == 4:
                values[item_type] = int.from_bytes(data[offset : offset + 4], "big")
            offset += item_size
        if record_type == 3:  # XQX_START_PAGE
            x_dpi = values.get(0x20000008, 0)
            y_dpi = values.get(0x20000009, 0)
            bits_per_pixel = values.get(0x2000000A, 1)
            if bits_per_pixel not in {1, 2, 4, 8}:
                return None
            return _validated_dpi(x_dpi * bits_per_pixel, y_dpi)
    return None


def _hbpl_dpi(data: bytes) -> tuple[int, int] | None:
    resolution = _pjl_dpi(data)
    if not resolution:
        return None
    match = re.search(
        rb"@PJL\s+SET\s+BITSPERPIXEL\s*=\s*(\d+)\b",
        data[:64 * 1024].upper(),
    )
    bits_per_pixel = int(match.group(1)) if match else 1
    if bits_per_pixel not in {1, 2, 4, 8}:
        return None
    # hbpldecode expands packed horizontal samples into a one-bit PBM plane.
    return _validated_dpi(resolution[0] * bits_per_pixel, resolution[1])


def _lavaflow_dpi(data: bytes) -> tuple[int, int] | None:
    sample = data[:64 * 1024]
    marker = re.search(rb"\x1b\*g8W(.{8})", sample, re.DOTALL)
    if marker:
        payload = marker.group(1)
        resolution = _validated_dpi(
            int.from_bytes(payload[2:4], "big"),
            int.from_bytes(payload[4:6], "big"),
        )
        if resolution:
            return resolution
    horizontal = re.search(rb"\x1b&u(\d{2,4})D", sample, re.IGNORECASE)
    if horizontal:
        return _validated_dpi(int(horizontal.group(1)), 600)
    return None


def _opl_dpi(data: bytes) -> tuple[int, int] | None:
    match = re.search(
        rb"(?:^|;)Resolution\s*=\s*(\d{2,4})x(\d{2,4})(?:;|$)",
        data[:64 * 1024],
        re.IGNORECASE,
    )
    if not match:
        return None
    return _validated_dpi(int(match.group(1)), int(match.group(2)))


def _slx_dpi(data: bytes) -> tuple[int, int] | None:
    magic = data.find(b"\xa5SLX", 0, 256)
    if magic < 0:
        return None
    offset = magic + 4
    for _ in range(128):
        if offset + 16 > len(data):
            return None
        record_size = int.from_bytes(data[offset : offset + 4], "big")
        record_type = int.from_bytes(data[offset + 4 : offset + 8], "big")
        item_count = int.from_bytes(data[offset + 8 : offset + 12], "big")
        if record_size < 16 or record_size > len(data) - offset or item_count > 1024:
            return None
        record_end = offset + record_size
        item_offset = offset + 16
        values: dict[int, int] = {}
        for _ in range(item_count):
            if item_offset + 8 > record_end:
                return None
            item_size = int.from_bytes(data[item_offset : item_offset + 4], "big")
            item_type = data[item_offset + 6]
            item_code = int.from_bytes(data[item_offset + 4 : item_offset + 6], "big")
            if item_size < 8 or item_size > record_end - item_offset:
                return None
            if item_type in {1, 2} and item_size >= 12:
                values[item_code] = int.from_bytes(
                    data[item_offset + 8 : item_offset + 12], "big"
                )
            item_offset += item_size
        if record_type == 2:  # SLT_START_PAGE
            return _validated_dpi(values.get(0x105, 0), values.get(0x106, 0))
        offset += (record_size + 3) & ~3
    return None


def _oakt_dpi(data: bytes) -> tuple[int, int] | None:
    resolution, _ = _oakt_page_metadata(data)
    return resolution


def _oakt_page_metadata(data: bytes) -> tuple[tuple[int, int] | None, str]:
    offset = data.find(b"OAKT", 0, 4096)
    if offset < 0:
        return None, "none"
    resolution: tuple[int, int] | None = None
    transform = "none"
    for _ in range(256):
        if offset + 12 > len(data) or data[offset : offset + 4] != b"OAKT":
            return resolution, transform
        record_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        record_type = int.from_bytes(data[offset + 8 : offset + 12], "little")
        if record_size < 12 or record_size > len(data) - offset:
            return None, "none"
        if record_type == 0x2B and record_size >= 12 + 4 * 4:
            paper = data[offset + 12 : offset + 12 + 4 * 4]
            paper_width = int.from_bytes(paper[4:8], "little")
            paper_height = int.from_bytes(paper[8:12], "little")
            orientation = int.from_bytes(paper[12:16], "little")
            transform = (
                "rotate_90"
                if orientation & 1 or paper_width > paper_height
                else "mirror_horizontal"
            )
        if record_type in {0x32, 0x33} and record_size >= 12 + 7 * 4:
            payload = data[offset + 12 : offset + 12 + 7 * 4]
            values = [
                int.from_bytes(payload[index : index + 4], "little")
                for index in range(0, len(payload), 4)
            ]
            resolution = _validated_dpi(values[4], values[5])
            if transform != "none":
                return resolution, transform
        offset += record_size
    return resolution, transform


def _pjl_dpi(data: bytes) -> tuple[int, int] | None:
    sample = data[:64 * 1024].upper()
    horizontal = re.search(rb"@PJL\s+SET\s+RESOLUTION\s*=\s*(\d{2,4})\b", sample)
    if not horizontal:
        return None
    vertical = re.search(rb"@PJL\s+SET\s+RESOLUTION\s*=\s*V(\d{2,4})\b", sample)
    x_dpi = int(horizontal.group(1))
    y_dpi = int(vertical.group(1)) if vertical else x_dpi
    return _validated_dpi(x_dpi, y_dpi)


def _validated_dpi(x_dpi: int, y_dpi: int) -> tuple[int, int] | None:
    if 72 <= x_dpi <= 9600 and 72 <= y_dpi <= 9600:
        return x_dpi, y_dpi
    return None
