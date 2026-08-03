from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


GADGET_MODES = frozenset({"msc", "printer", "msc_hid", "printer_hid"})


def is_msc_mode(mode: str) -> bool:
    return mode in {"msc", "msc_hid"}


def has_hid(mode: str) -> bool:
    return mode in {"msc_hid", "printer_hid"}


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
    port: int = 8443
    tls_cert: str = "/etc/gadget-msc-printer/tls.crt"
    tls_key: str = "/etc/gadget-msc-printer/tls.key"
    username: str = "tejian01"
    password: str = "julei123#"
    session_hours: int = 8
    static_dir: str = "/opt/gadget-msc-printer/portal/portal/dist"


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
    device: str = "/dev/g_printer0"
    output_dir: str = "/var/lib/gadget-msc-printer/print_jobs"
    usb_vendor_id: str = "0x0525"
    usb_product_id: str = "0xa4a8"
    usb_manufacturer: str = "KICKPI"
    usb_product: str = "K2B USB Printer"
    usb_serial: str = "K2B-H618-PRINTER-001"
    usb_pnp_string: str = "MFG:KICKPI;MDL:K2B USB Printer;DES:K2B USB Printer;CMD:PJL,PCL,PCLXL,POSTSCRIPT,RAW;CLS:PRINTER;"
    idle_complete_seconds: float = 20.0
    min_job_bytes: int = 128
    chunk_size: int = 65536


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
    device: DeviceConfig = field(default_factory=DeviceConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    msc: MscConfig = field(default_factory=MscConfig)
    printer: PrinterConfig = field(default_factory=PrinterConfig)
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
        device=_merge_dataclass(DeviceConfig, data.get("device", {})),
        upload=_merge_dataclass(UploadConfig, data.get("upload", {})),
        cleanup=_merge_dataclass(CleanupConfig, data.get("cleanup", {})),
        msc=_merge_dataclass(MscConfig, data.get("msc", {})),
        printer=_merge_dataclass(PrinterConfig, data.get("printer", {})),
        pdf=_merge_dataclass(PdfConfig, data.get("pdf", {})),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    if config.gadget.mode not in GADGET_MODES:
        raise ValueError("gadget.mode must be msc, printer, msc_hid, or printer_hid")
    if not 1 <= config.web.port <= 65535:
        raise ValueError("web.port must be between 1 and 65535")
    if config.web.port != 8443:
        raise ValueError("web.port must be 8443")
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
    if config.cleanup.interval_hours < 1:
        raise ValueError("cleanup.interval_hours must be at least 1")
    if config.cleanup.report_retention_days < 1:
        raise ValueError("cleanup.report_retention_days must be at least 1")
    if config.cleanup.log_retention_days < 1:
        raise ValueError("cleanup.log_retention_days must be at least 1")


def save_config(path: str | Path, config: AppConfig) -> None:
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
