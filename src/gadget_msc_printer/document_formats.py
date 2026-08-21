from __future__ import annotations

import re
import zipfile
from pathlib import Path


HPGL_PROBE_BYTES = 64 * 1024
XPS_CONTENT_TYPES_LIMIT = 1024 * 1024
XPS_MAX_MEMBERS = 10_000
MODERN_FORMAT_PROBE_BYTES = 512
PJL_LANGUAGE_RE = re.compile(rb"ENTER\s+LANGUAGE\s*=\s*([A-Z0-9_./-]+)")
ESCP2_REMOTE_PREFIX = b"\x1b(R\x08\x00\x00REMOTE1"
_ESCP2_PROFILE_SIGNATURES = (
    (
        "xp410",
        ESCP2_REMOTE_PREFIX
        + b"PM\x02\x00\x00\x00SN\x03\x00\x00\x00\x01\x1b\x00\x00\x00",
        "匹配Gutenprint c8x/c82系列PM/SN初始化指纹；已验证XP-440、L120、L310和ET-2750",
    ),
    (
        "sr800",
        ESCP2_REMOTE_PREFIX
        + b"IR\x02\x00\x00\x01EX\x06\x00\x00\x00\x00\x00\x05\x00"
        + b"PP\x03\x00\x00\x01\xff\x1b\x00\x00\x00",
        "匹配Gutenprint Stylus Photo R800 IR/EX/PP初始化指纹",
    ),
)
_HPGL_COMMAND_RE = re.compile(rb"(?:^|;)\s*([A-Z]{2})(?=[^A-Z]|$)")
_HPGL_COMMANDS = {
    b"AA",
    b"AR",
    b"BP",
    b"CI",
    b"DF",
    b"DI",
    b"DR",
    b"DT",
    b"EA",
    b"ER",
    b"IN",
    b"IP",
    b"IW",
    b"LA",
    b"LB",
    b"LT",
    b"PA",
    b"PD",
    b"PG",
    b"PR",
    b"PU",
    b"RA",
    b"RO",
    b"RR",
    b"SC",
    b"SI",
    b"SL",
    b"SP",
    b"SR",
    b"SS",
    b"VS",
    b"WU",
}
_HPGL_SETUP_COMMANDS = {b"BP", b"DF", b"IN", b"IP", b"RO", b"SC", b"SP"}
_HPGL_DRAW_COMMANDS = {b"AA", b"AR", b"CI", b"EA", b"ER", b"LB", b"PA", b"PD", b"PR", b"PU", b"RA", b"RR"}


def detect_c_printer_protocol(data: bytes) -> str | None:
    """Recognize C-group vendor/private printer languages conservatively.

    These protocols are intentionally identification-only in the first
    offline implementation.  A short marker is not enough evidence: the
    detector requires either an explicit PJL/vendor declaration or a small
    structural signature so ordinary report text is not mislabeled.
    """

    if not data:
        return None
    sample = data[:HPGL_PROBE_BYTES]
    upper = sample.upper()
    header_upper = upper[:4096]
    language = declared_pjl_language(sample)
    stripped = sample.lstrip(b"\x00\x04\x09\x0a\x0c\x0d\x20")
    if stripped.startswith((b"%PDF-", b"%!")) or detect_modern_print_format(sample):
        return None
    if detect_image_format(stripped):
        return None
    if language in {
        "PCL",
        "PCL3",
        "PCL3GUI",
        "PCLGUI",
        "PCLXL",
        "PCL6",
        "POSTSCRIPT",
        "PS",
        "HPGL",
        "HPGL2",
        "HP-GL",
        "HP-GL2",
        "ESC/P",
        "ESCP",
        "ESC/P2",
        "ESCP2",
        "ESC/P-R",
        "ESCP-R",
        "ESCPR",
        "ESC/PAGE",
        "ESCPAGE",
    }:
        return None

    if language in {"UFR", "UFRII", "UFRII-LT"}:
        return "ufr"
    if language in {"CAPT", "CAPT2", "CAPT3"}:
        return "capt"
    if re.search(rb"(?:^|[^A-Z0-9])UFR(?:II|\s+II)(?:-?LT)?(?:[^A-Z0-9]|$)", header_upper):
        return "ufr"
    if re.search(rb"(?:^|[^A-Z0-9])CAPT(?:2|3)?(?:[^A-Z0-9]|$)", header_upper):
        return "capt"

    if language in {"RPCS", "RPCS2", "RPCS-II", "RPCSIII", "RPCS-III"}:
        return "ricoh_rpcs"
    if b"RPCS" in header_upper and b"RICOH" in header_upper:
        return "ricoh_rpcs"

    # SPLC is shared by multiple vendors.  Require an explicit Sharp vendor
    # marker before separating it from the existing Samsung SPL/QPDL path.
    if language in {"SPLC", "SPL-C", "SHARPSPLC", "SHARP-SPLC"} and b"SHARP" in header_upper:
        return "sharp_splc"
    if header_upper.lstrip(b"\x00\x04\x09\x0a\x0c\x0d\x20").startswith(b"SHARP") and (
        b"SPLC" in header_upper or b"SPL-C" in header_upper
    ):
        return "sharp_splc"

    if language in {"PANTUM", "PANTUM-GDI", "PANTUM_GDI", "GDI"}:
        if b"PANTUM" in upper or language != "GDI":
            return "pantum_gdi"
    if (
        b"PANTUM" in header_upper
        and b"GDI" in header_upper
        and (
            re.search(rb"@PJL[^\r\n]{0,256}PANTUM[^\r\n]{0,64}GDI", header_upper)
            or header_upper.lstrip(b"\x00\x04\x09\x0a\x0c\x0d\x20").startswith(b"PANTUM")
        )
    ):
        return "pantum_gdi"

    if _looks_like_afp(sample):
        return "ibm_afp"
    if language == "PRINTREX" or header_upper.lstrip(
        b"\x00\x04\x09\x0a\x0c\x0d\x20"
    ).startswith((b"PRINTREX", b"PRNTRX")):
        return "printrex"

    if _looks_like_zpl(sample):
        return "zpl"
    if _looks_like_cpcl(sample):
        return "cpcl"
    if _looks_like_epl(sample):
        return "epl"
    return None


def _looks_like_afp(data: bytes) -> bool:
    """Require two contiguous AFP structured fields, not just byte 0x5A."""

    position = 0
    records = 0
    while position + 8 <= len(data) and records < 4:
        if data[position] != 0x5A:
            break
        length = int.from_bytes(data[position + 1 : position + 3], "big")
        if length < 8 or length > len(data) - position or data[position + 3] != 0xD3:
            break
        records += 1
        position += length
    return records >= 2


def _looks_like_zpl(data: bytes) -> bool:
    if b"^XA" not in data:
        return False
    markers = (b"^FO", b"^FD", b"^FS", b"^GB", b"^BC", b"^B3", b"^GF", b"^A")
    return sum(marker in data for marker in markers) >= 2 and (
        b"^XZ" in data or b"^FS" in data or b"^FD" in data
    )


def _looks_like_cpcl(data: bytes) -> bool:
    lines = [line.strip().upper() for line in data.splitlines()[:256]]
    if not any(line.startswith((b"! 0 ", b"! U1 ", b"! U1")) for line in lines):
        return False
    has_print = any(line == b"PRINT" or line.startswith(b"PRINT ") for line in lines)
    commands = sum(
        line.startswith((b"T ", b"TEXT ", b"B ", b"EG ", b"GW ", b"PW "))
        for line in lines
    )
    return has_print and commands >= 1


def _looks_like_epl(data: bytes) -> bool:
    lines = [line.strip() for line in data.splitlines()[:256] if line.strip()]
    if not lines or lines[0] != b"N":
        return False
    content_commands = sum(
        re.match(rb"(?:A|B|b)\d+,", line) is not None or line.startswith(b"GW")
        for line in lines[1:]
    )
    print_commands = sum(re.fullmatch(rb"P\d+(?:,\d+)?", line) is not None for line in lines)
    return content_commands >= 1 and print_commands == 1


def detect_modern_print_format(data: bytes) -> str | None:
    """Recognize driverless raster and PDF-based printer streams."""

    sample = data[:MODERN_FORMAT_PROBE_BYTES]
    if sample.startswith(b"RaS2PwgRaster\x00"):
        return "pwg_raster"
    if sample.startswith((b"RaSt", b"tSaR", b"RaS2", b"2SaR", b"RaS3", b"3SaR")):
        return "cups_raster"
    if sample.startswith(b"UNIRAST\x00"):
        return "apple_urf"
    if sample.startswith(b"%PDF-") and re.search(
        rb"%\s*PCLM(?:\s|$)", sample.upper()
    ):
        return "pclm"
    return None


def detect_image_format(data: bytes) -> str | None:
    """Recognize image payloads that are commonly saved with a PRN suffix."""

    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 14 and data.startswith(b"BM"):
        return "bmp"
    if data.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")):
        return "tiff"
    if data.startswith(b"\xb1\x68\xde\x3a"):
        return "dcx"
    if (
        len(data) >= 128
        and data[0] == 0x0A
        and data[1] in {0, 2, 3, 4, 5}
        and data[2] == 1
        and data[3] in {1, 2, 4, 8}
    ):
        return "pcx"
    return None


def declared_pjl_language(data: bytes) -> str:
    match = PJL_LANGUAGE_RE.search(data.upper())
    return match.group(1).decode("ascii") if match else ""


def looks_like_pcl3gui(data: bytes) -> bool:
    language = declared_pjl_language(data)
    return language in {"PCL3", "PCL3GUI", "PCLGUI"} or b"PCL3GUI" in data.upper()


def detect_epson_protocol(data: bytes) -> str | None:
    """Conservatively distinguish Epson printer-language families.

    ESC/P, ESC/P2, ESC/P-R and ESC/Page are different languages. An EJL
    wrapper alone is not enough evidence to claim that its payload is ESC/P2.
    """

    if not data:
        return None
    sample = data[:HPGL_PROBE_BYTES]
    upper = sample.upper()
    language = declared_pjl_language(sample)

    escpr_binary_markers = (
        b"\x1b(R\x06\x00\x00ESCPR",
        b"\x1bq\x09\x00\x00\x00setq",
        b"\x1bp\x00\x00\x00\x00sttp",
        b"\x1bd",
    )
    if language in {"ESC/P-R", "ESCP-R", "ESCPR"} or any(
        marker in upper for marker in (b"ESC/P-R", b"ESCP-R")
    ):
        return "escpr"
    if b"ESCPRLIB" in upper and sum(marker in sample for marker in escpr_binary_markers) >= 2:
        return "escpr"
    if sum(marker in sample for marker in escpr_binary_markers) >= 3:
        return "escpr"
    if language in {"ESC/PAGE", "ESCPAGE"} or any(
        marker in upper for marker in (b"ESC/PAGE", b"ESCPAGE")
    ):
        return "escpage"
    if language in {"ESC/P2", "ESCP2"}:
        return "escp2"
    if language in {"ESC/P", "ESCP"}:
        return "escp"

    escp2_markers = (
        b"\x1b(G",
        b"\x1b(U",
        b"\x1b(C",
        b"\x1b(c",
        b"\x1b(V",
        b"\x1b(v",
        b"\x1b(i",
        b"\x1b.",
    )
    if b"\x1b@" in sample and sum(marker in sample for marker in escp2_markers) >= 2:
        return "escp2"

    classic_markers = (
        b"\x1b*",
        b"\x1b3",
        b"\x1bA",
        b"\x1bD",
        b"\x1bM",
        b"\x1bP",
        b"\x1bW",
        b"\x1b!",
    )
    if sample.lstrip(b"\x00\x04\x09\x0a\x0c\x0d\x20").startswith(b"\x1b@") and sum(
        marker in sample for marker in classic_markers
    ) >= 2:
        return "escp"

    if b"@EJL" in upper or b"EPSON EPL" in upper:
        return "epson"
    return None


def detect_escp2_profile_hint(data: bytes) -> tuple[str | None, str]:
    """Return only profiles backed by exact, validated driver fingerprints."""

    sample = data[:4096]
    if detect_epson_protocol(sample) != "escp2":
        return None, "不是可识别的ESC/P2打印流"
    for profile, signature, evidence in _ESCP2_PROFILE_SIGNATURES:
        if signature in sample:
            return profile, evidence
    return None, "未匹配已验证的ESC/P2初始化指纹，需手动选择Profile"


def looks_like_hpgl(data: bytes) -> bool:
    """Conservatively recognize standalone or PCL-wrapped HP-GL/2."""

    if not data:
        return False
    sample = data[:HPGL_PROBE_BYTES]
    upper = sample.upper()
    if re.search(rb"ENTER\s+LANGUAGE\s*=\s*HP-?GL(?:2)?\b", upper):
        return True
    if b"\x1b%0B" in sample:
        return True

    candidate = upper.lstrip(b"\x00\x04\x09\x0a\x0c\x0d\x20")
    commands = _HPGL_COMMAND_RE.findall(candidate)
    known = [command for command in commands if command in _HPGL_COMMANDS]
    if len(known) < 4:
        return False
    if not any(command in _HPGL_DRAW_COMMANDS for command in known):
        return False
    if candidate.startswith((b"IN;", b"BP;", b"DF;")):
        return True
    return any(command in _HPGL_SETUP_COMMANDS for command in known) and len(known) >= 6


def detect_xps_package(path: str | Path) -> str | None:
    """Return ``xps`` or ``oxps`` for a structurally valid fixed-page OPC package."""

    source = Path(path)
    try:
        with source.open("rb") as handle:
            if handle.read(4) not in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}:
                return None
        with zipfile.ZipFile(source) as package:
            members = package.infolist()
            if not members or len(members) > XPS_MAX_MEMBERS:
                return None
            by_name = {
                info.filename.replace("\\", "/").lower(): info for info in members
            }
            content_info = by_name.get("[content_types].xml")
            if content_info is None or content_info.flag_bits & 0x1:
                return None
            if content_info.file_size > XPS_CONTENT_TYPES_LIMIT:
                return None
            names = tuple(by_name)
            if not any(name.endswith(".fdseq") for name in names):
                return None
            if not any(name.endswith(".fpage") for name in names):
                return None
            with package.open(content_info) as handle:
                content_types = handle.read(XPS_CONTENT_TYPES_LIMIT + 1).lower()
            if len(content_types) > XPS_CONTENT_TYPES_LIMIT:
                return None
            if b"application/vnd.openxps" in content_types:
                return "oxps"
            if b"application/vnd.ms-package.xps" in content_types:
                return "xps"
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return None
    return None
