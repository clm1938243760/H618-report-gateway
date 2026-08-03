from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .config import DeviceConfig, atomic_write_text


@dataclass(frozen=True)
class ReportInfoSnapshot:
    content: bytes
    sha256: str
    device_code: str
    exam_doct: str
    exam_doct_code: str


class ReportInfoManager:
    def __init__(self, config: DeviceConfig) -> None:
        self.config = config

    @property
    def path(self) -> Path:
        return Path(self.config.report_info_path)

    def write(self, device_code: str, exam_doct: str, exam_doct_code: str) -> ReportInfoSnapshot:
        device_code = _validate_value("DeviceCode", device_code)
        exam_doct = _validate_value("ExamDoct", exam_doct)
        exam_doct_code = _validate_value("ExamDoctCode", exam_doct_code)
        root = ET.Element("UploadReportInfo")
        ET.SubElement(root, "DeviceCode").text = device_code
        ET.SubElement(root, "ExamDoct").text = exam_doct
        ET.SubElement(root, "ExamDoctCode").text = exam_doct_code
        body = ET.tostring(root, encoding="unicode", short_empty_elements=False)
        text = f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'
        atomic_write_text(self.path, text, mode=0o640)
        return self.snapshot()

    def ensure(self) -> bool:
        if self.path.exists():
            try:
                self.snapshot()
                return True
            except ValueError:
                pass
        if (
            not self.config.device_code.strip()
            or not self.config.exam_doct.strip()
            or not self.config.exam_doct_code.strip()
        ):
            return False
        self.write(self.config.device_code, self.config.exam_doct, self.config.exam_doct_code)
        return True

    def snapshot(self) -> ReportInfoSnapshot:
        try:
            content = self.path.read_bytes()
        except FileNotFoundError as exc:
            raise ValueError("ReportInfo.xml does not exist") from exc
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ValueError(f"ReportInfo.xml is invalid: {exc}") from exc
        if root.tag != "UploadReportInfo":
            raise ValueError("ReportInfo.xml root must be UploadReportInfo")
        root_start = content.find(b"<UploadReportInfo")
        root_end = content.find(b">", root_start)
        root_declaration = content[root_start:root_end] if root_start >= 0 and root_end >= 0 else b""
        if root.attrib or b"xmlns" in root_declaration:
            raise ValueError("ReportInfo.xml root must not contain namespace attributes")
        child_tags = [child.tag for child in root]
        if child_tags != ["DeviceCode", "ExamDoct", "ExamDoctCode"]:
            raise ValueError("ReportInfo.xml must contain DeviceCode, ExamDoct and ExamDoctCode in order")
        device_code = _validate_value("DeviceCode", root.findtext("DeviceCode", ""))
        exam_doct = _validate_value("ExamDoct", root.findtext("ExamDoct", ""))
        exam_doct_code = _validate_value("ExamDoctCode", root.findtext("ExamDoctCode", ""))
        return ReportInfoSnapshot(
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            device_code=device_code,
            exam_doct=exam_doct,
            exam_doct_code=exam_doct_code,
        )


def _validate_value(name: str, value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    if len(normalized) > 128:
        raise ValueError(f"{name} must not exceed 128 characters")
    if any(ord(char) < 32 and char not in "\t\r\n" for char in normalized):
        raise ValueError(f"{name} contains invalid control characters")
    return normalized
