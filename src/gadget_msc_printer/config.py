from __future__ import annotations

import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

import yaml


GADGET_MODES = frozenset({"msc", "printer", "msc_hid", "printer_hid"})
PRINTER_DRIVER_COMMANDS = {
    "universal": "PJL,PCL,PCLXL,POSTSCRIPT,RAW",
    "pcl": "PJL,PCL,PCLXL,RAW",
    "postscript": "PJL,POSTSCRIPT,RAW",
    "raw": "RAW",
}
PHYSICAL_PRINTER_DRIVER_PROFILES = frozenset(
    {
        "ipp_everywhere",
        "hp_laserjet_m401_pcl6",
        "brother_hl1200",
        "generic_postscript",
        "generic_pcl",
        "generic_pcl6",
    }
)


def is_supported_physical_printer_driver(profile: str) -> bool:
    """Accept bundled profiles and reviewed driver records only.

    A ``custom:`` value is never an arbitrary command or file path.  The CUPS
    layer resolves it through the reviewed local driver registry before use.
    """

    return profile in PHYSICAL_PRINTER_DRIVER_PROFILES or re.fullmatch(
        r"custom:[a-z0-9][a-z0-9._-]{0,127}", profile
    ) is not None
FIXED_PRINTER_VENDOR_ID = "0x0525"
FIXED_PRINTER_PRODUCT_ID = "0xa4a8"
FIXED_PRINTER_MANUFACTURER = "JVLEI"


def is_msc_mode(mode: str) -> bool:
    return mode in {"msc", "msc_hid"}


def has_hid(mode: str) -> bool:
    return mode in {"msc_hid", "printer_hid"}


def build_printer_pnp_string(config: "PrinterConfig") -> str:
    commands = PRINTER_DRIVER_COMMANDS[config.driver_profile]
    return (
        f"MFG:{FIXED_PRINTER_MANUFACTURER};"
        f"MDL:{config.usb_product};"
        f"DES:{config.usb_product};"
        f"CMD:{commands};CLS:PRINTER;"
    )


def normalize_printer_identity(config: "PrinterConfig") -> None:
    config.usb_vendor_id = FIXED_PRINTER_VENDOR_ID
    config.usb_product_id = FIXED_PRINTER_PRODUCT_ID
    config.usb_manufacturer = FIXED_PRINTER_MANUFACTURER
    if config.driver_profile in PRINTER_DRIVER_COMMANDS:
        config.usb_pnp_string = build_printer_pnp_string(config)


@dataclass
class RuntimeConfig:
    data_dir: str = "/var/lib/gadget-msc-printer"
    poll_interval_seconds: float = 2.0
    log_level: str = "INFO"


@dataclass
class GadgetConfig:
    mode: str = "msc"
    udc_device: str = "auto"
    msc_gadget_dir: str = "/sys/kernel/config/usb_gadget/gmp_msc"
    printer_gadget_dir: str = "/sys/kernel/config/usb_gadget/gmp_printer"
    apply_command: str = "/opt/gadget-msc-printer/scripts/apply_gadget_mode.sh"


@dataclass
class WebConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 443
    compatibility_port: int = 8443
    tls_cert: str = "/etc/gadget-msc-printer/tls.crt"
    tls_key: str = "/etc/gadget-msc-printer/tls.key"
    username: str = "tejian01"
    password: str = "julei123#"
    session_hours: int = 8
    static_dir: str = "/opt/gadget-msc-printer/portal/portal/dist"


@dataclass
class HotspotConfig:
    device: str = "wlan1"
    connection_name: str = "gmp-hotspot"
    ssid: str = "JVLEI-Gateway"
    password: str = "julei123#"
    autostart: bool = False
    idle_timeout_minutes: int = 30
    address: str = "192.168.0.1/24"


@dataclass
class DeviceConfig:
    device_code: str = ""
    exam_doct: str = ""
    exam_doct_code: str = ""
    report_info_path: str = "/var/lib/gadget-msc-printer/device/ReportInfo.xml"


@dataclass
class UploadConfig:
    enabled: bool = True
    deduplicate: bool = True
    endpoint: str = "http://192.168.112.139:9061/api/client/uploadOriginalReport"
    hospital_code: str = "tejian01"
    state_db: str = "/var/lib/gadget-msc-printer/state/jobs.sqlite3"
    poll_interval_seconds: float = 5.0
    file_stable_seconds: float = 2.0
    timeout_seconds: int = 30
    retry_interval_seconds: int = 60
    max_attempts: int = 3
    user_agent: str = "K2B-H618-Gadget-Gateway"


@dataclass
class CleanupConfig:
    enabled: bool = True
    interval_hours: int = 24
    report_retention_days: int = 30
    log_retention_days: int = 14


@dataclass
class MscConfig:
    enabled: bool = True
    deduplicate: bool = True
    auto_delete: bool = False
    restore_protected_files: bool = True
    protected_files: list[str] = field(default_factory=list)
    protected_seed_dir: str = "/var/lib/gadget-msc-printer/msc_protected"
    gadget_dir: str = "/sys/kernel/config/usb_gadget/gmp_msc"
    udc_device: str = "auto"
    image_path: str = "/var/lib/gadget-msc-printer/msc/ums_shared.img"
    image_size_mb: int = 512
    label: str = "USB DISK"
    mount_dir: str = "/var/lib/gadget-msc-printer/msc_mount"
    output_dir: str = "/var/lib/gadget-msc-printer/msc_files"
    state_dir: str = "/var/lib/gadget-msc-printer/state/msc"
    stable_seconds: float = 2.0
    quiet_seconds: float = 2.0
    copy_recursive: bool = True
    ignore_names: list[str] = field(default_factory=lambda: ["System Volume Information", "$RECYCLE.BIN"])
    report_extensions: list[str] = field(
        default_factory=lambda: [".pdf", ".bmp", ".jpg", ".jpeg", ".png", ".dat", ".txt", ".csv", ".xml"]
    )


@dataclass
class PrinterConfig:
    enabled: bool = True
    driver_profile: str = "universal"
    device: str = "/dev/g_printer0"
    output_dir: str = "/var/lib/gadget-msc-printer/print_jobs"
    usb_vendor_id: str = FIXED_PRINTER_VENDOR_ID
    usb_product_id: str = FIXED_PRINTER_PRODUCT_ID
    usb_manufacturer: str = FIXED_PRINTER_MANUFACTURER
    usb_product: str = "K2B USB Printer"
    usb_serial: str = "K2B-H618-PRINTER-001"
    usb_pnp_string: str = "MFG:JVLEI;MDL:K2B USB Printer;DES:K2B USB Printer;CMD:PJL,PCL,PCLXL,POSTSCRIPT,RAW;CLS:PRINTER;"
    idle_complete_seconds: float = 20.0
    min_job_bytes: int = 128
    chunk_size: int = 65536


@dataclass
class PhysicalPrinterConfig:
    enabled: bool = False
    auto_print: bool = False
    queue_name: str = "Physical_Printer"
    device_uri: str = ""
    driver_profile: str = "hp_laserjet_m401_pcl6"
    page_size: str = "A4"
    resolution: str = "600dpi"
    copies: int = 1
    set_default: bool = True
    state_db: str = "/var/lib/gadget-msc-printer/state/physical_print_jobs.sqlite3"
    poll_interval_seconds: float = 0.5
    file_stable_seconds: float = 2.0
    retry_interval_seconds: int = 60
    max_attempts: int = 3


@dataclass
class PdfConfig:
    enabled: bool = True
    output_dir: str = "/var/lib/gadget-msc-printer/reports_pdf"
    ghostpcl: list[str] = field(default_factory=lambda: ["gpcl6", "pcl6"])
    ps2pdf: str = "ps2pdf"


@dataclass
class AppConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    gadget: GadgetConfig = field(default_factory=GadgetConfig)
    web: WebConfig = field(default_factory=WebConfig)
    hotspot: HotspotConfig = field(default_factory=HotspotConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    msc: MscConfig = field(default_factory=MscConfig)
    printer: PrinterConfig = field(default_factory=PrinterConfig)
    physical_printer: PhysicalPrinterConfig = field(default_factory=PhysicalPrinterConfig)
    pdf: PdfConfig = field(default_factory=PdfConfig)


def resolve_udc_device(
    configured: str,
    sys_class_udc: str | Path = "/sys/class/udc",
) -> str:
    value = configured.strip()
    if value and value.lower() != "auto":
        return value

    root = Path(sys_class_udc)
    try:
        candidates = sorted(path.name for path in root.iterdir())
    except FileNotFoundError:
        candidates = []

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise RuntimeError("no USB device controller found in /sys/class/udc")
    raise RuntimeError(
        "multiple USB device controllers found; set gadget.udc_device explicitly: "
        + ", ".join(candidates)
    )


def _merge_dataclass(cls, values: dict[str, Any]):
    valid = {item.name for item in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return cls(**{key: value for key, value in values.items() if key in valid})


def load_config(path: str | Path) -> AppConfig:
    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    config = AppConfig(
        runtime=_merge_dataclass(RuntimeConfig, data.get("runtime", {})),
        gadget=_merge_dataclass(GadgetConfig, data.get("gadget", {})),
        web=_merge_dataclass(WebConfig, data.get("web", {})),
        hotspot=_merge_dataclass(HotspotConfig, data.get("hotspot", {})),
        device=_merge_dataclass(DeviceConfig, data.get("device", {})),
        upload=_merge_dataclass(UploadConfig, data.get("upload", {})),
        cleanup=_merge_dataclass(CleanupConfig, data.get("cleanup", {})),
        msc=_merge_dataclass(MscConfig, data.get("msc", {})),
        printer=_merge_dataclass(PrinterConfig, data.get("printer", {})),
        physical_printer=_merge_dataclass(PhysicalPrinterConfig, data.get("physical_printer", {})),
        pdf=_merge_dataclass(PdfConfig, data.get("pdf", {})),
    )
    normalize_printer_identity(config.printer)
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    if config.gadget.mode not in GADGET_MODES:
        raise ValueError("gadget.mode must be msc, printer, msc_hid, or printer_hid")
    if not 1 <= config.web.port <= 65535:
        raise ValueError("web.port must be between 1 and 65535")
    if config.web.port != 443:
        raise ValueError("web.port must be 443")
    if not 0 <= config.web.compatibility_port <= 65535:
        raise ValueError("web.compatibility_port must be 0 or a valid TCP port")
    if config.web.compatibility_port == config.web.port:
        raise ValueError("web.compatibility_port must differ from web.port")
    if not config.web.username.strip():
        raise ValueError("web.username must not be empty")
    if len(config.web.username) > 128:
        raise ValueError("web.username must not exceed 128 characters")
    if len(config.web.password) < 8:
        raise ValueError("web.password must contain at least 8 characters")
    if len(config.web.password) > 256:
        raise ValueError("web.password is too long")
    if not config.web.static_dir.strip():
        raise ValueError("web.static_dir must not be empty")
    if not config.hotspot.ssid.strip() or len(config.hotspot.ssid.encode("utf-8")) > 32:
        raise ValueError("hotspot.ssid must contain 1 to 32 bytes")
    if any(char in config.hotspot.ssid for char in "\r\n"):
        raise ValueError("hotspot.ssid contains invalid characters")
    if not 8 <= len(config.hotspot.password) <= 63 or any(
        char in config.hotspot.password for char in "\r\n"
    ):
        raise ValueError("hotspot.password must contain 8 to 63 characters")
    for name, value in (
        ("hotspot.device", config.hotspot.device),
        ("hotspot.connection_name", config.hotspot.connection_name),
    ):
        if not value or len(value) > 32 or not all(char.isalnum() or char in "_.-" for char in value):
            raise ValueError(f"{name} contains invalid characters")
    if not 0 <= config.hotspot.idle_timeout_minutes <= 1440:
        raise ValueError("hotspot.idle_timeout_minutes must be between 0 and 1440")
    if config.hotspot.address != "192.168.0.1/24":
        raise ValueError("hotspot.address must be 192.168.0.1/24")
    if config.upload.enabled:
        parsed = urlparse(config.upload.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("upload.endpoint must be an HTTP or HTTPS URL")
        if not config.upload.hospital_code.strip():
            raise ValueError("upload.hospital_code must not be empty")
        if len(config.upload.hospital_code.strip()) > 128:
            raise ValueError("upload.hospital_code must not exceed 128 characters")
    for name, value in (
        ("device.device_code", config.device.device_code),
        ("device.exam_doct", config.device.exam_doct),
        ("device.exam_doct_code", config.device.exam_doct_code),
    ):
        if len(value.strip()) > 128:
            raise ValueError(f"{name} must not exceed 128 characters")
    if config.upload.max_attempts < 1:
        raise ValueError("upload.max_attempts must be at least 1")
    if config.upload.retry_interval_seconds < 1:
        raise ValueError("upload.retry_interval_seconds must be at least 1")
    if config.printer.driver_profile not in PRINTER_DRIVER_COMMANDS:
        raise ValueError("printer.driver_profile is not supported")
    if (
        config.printer.usb_vendor_id != FIXED_PRINTER_VENDOR_ID
        or config.printer.usb_product_id != FIXED_PRINTER_PRODUCT_ID
        or config.printer.usb_manufacturer != FIXED_PRINTER_MANUFACTURER
    ):
        raise ValueError("printer USB identity is fixed by the product firmware")
    for name, value in (
        ("printer.usb_vendor_id", config.printer.usb_vendor_id),
        ("printer.usb_product_id", config.printer.usb_product_id),
    ):
        if re.fullmatch(r"0x[0-9a-fA-F]{4}", value) is None:
            raise ValueError(f"{name} must use the form 0x1234")
    for name, value, maximum in (
        ("printer.usb_manufacturer", config.printer.usb_manufacturer, 64),
        ("printer.usb_product", config.printer.usb_product, 96),
        ("printer.usb_serial", config.printer.usb_serial, 64),
    ):
        if not value.strip() or len(value) > maximum or any(char in value for char in "\r\n;"):
            raise ValueError(f"{name} contains invalid text")
    if not 0.5 <= config.printer.idle_complete_seconds <= 120:
        raise ValueError("printer.idle_complete_seconds must be between 0.5 and 120")
    if not 1 <= config.printer.min_job_bytes <= 10 * 1024 * 1024:
        raise ValueError("printer.min_job_bytes must be between 1 and 10485760")
    if (
        not config.physical_printer.queue_name
        or len(config.physical_printer.queue_name) > 64
        or re.fullmatch(r"[A-Za-z0-9._-]+", config.physical_printer.queue_name) is None
    ):
        raise ValueError("physical_printer.queue_name contains invalid characters")
    if not is_supported_physical_printer_driver(config.physical_printer.driver_profile):
        raise ValueError("physical_printer.driver_profile is not supported")
    if config.physical_printer.device_uri:
        device_uri = urlparse(config.physical_printer.device_uri)
        if device_uri.scheme not in {"usb", "ipp", "ipps", "socket", "lpd"}:
            raise ValueError("physical_printer.device_uri must use usb, ipp, ipps, socket, or lpd")
        if len(config.physical_printer.device_uri) > 1024 or any(
            char in config.physical_printer.device_uri for char in "\r\n"
        ):
            raise ValueError("physical_printer.device_uri contains invalid characters")
    if config.physical_printer.enabled and not config.physical_printer.device_uri:
        raise ValueError("physical_printer.device_uri is required when physical printing is enabled")
    if config.physical_printer.auto_print and not config.physical_printer.enabled:
        raise ValueError("physical_printer.auto_print requires physical_printer.enabled")
    if config.physical_printer.page_size not in {"A4", "A5", "Letter"}:
        raise ValueError("physical_printer.page_size is not supported")
    if config.physical_printer.resolution not in {"300dpi", "600dpi", "1200dpi"}:
        raise ValueError("physical_printer.resolution is not supported")
    if not 1 <= config.physical_printer.copies <= 99:
        raise ValueError("physical_printer.copies must be between 1 and 99")
    if not 0.5 <= config.physical_printer.poll_interval_seconds <= 300:
        raise ValueError("physical_printer.poll_interval_seconds must be between 0.5 and 300")
    if not 0 <= config.physical_printer.file_stable_seconds <= 300:
        raise ValueError("physical_printer.file_stable_seconds must be between 0 and 300")
    if config.physical_printer.retry_interval_seconds < 1:
        raise ValueError("physical_printer.retry_interval_seconds must be at least 1")
    if config.physical_printer.max_attempts < 1:
        raise ValueError("physical_printer.max_attempts must be at least 1")
    if not 32 <= config.msc.image_size_mb <= 4096:
        raise ValueError("msc.image_size_mb must be between 32 and 4096")
    if not config.msc.label.strip() or len(config.msc.label.encode("ascii", errors="ignore")) != len(config.msc.label):
        raise ValueError("msc.label must contain ASCII characters")
    if len(config.msc.label) > 11 or any(char in config.msc.label for char in "\"*+,./:;<=>?[\\]|"):
        raise ValueError("msc.label must be a valid FAT label with at most 11 characters")
    for value in config.msc.protected_files:
        path = PurePosixPath(str(value).strip())
        if not str(value).strip() or path.is_absolute() or ".." in path.parts:
            raise ValueError("msc.protected_files must contain relative paths inside the U disk")
    if config.cleanup.interval_hours < 1:
        raise ValueError("cleanup.interval_hours must be at least 1")
    if config.cleanup.report_retention_days < 1:
        raise ValueError("cleanup.report_retention_days must be at least 1")
    if config.cleanup.log_retention_days < 1:
        raise ValueError("cleanup.log_retention_days must be at least 1")


def save_config(path: str | Path, config: AppConfig) -> None:
    normalize_printer_identity(config.printer)
    validate_config(config)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(asdict(config), allow_unicode=True, sort_keys=False)
    atomic_write_text(target, text, mode=0o640)


def atomic_write_text(path: str | Path, text: str, mode: int = 0o644) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
