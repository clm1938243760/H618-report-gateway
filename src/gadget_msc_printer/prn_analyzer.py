from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROTOCOL_LABELS = {
    "pdf": "PDF",
    "postscript": "PostScript",
    "pclxl": "PCL XL",
    "pcl": "PCL",
    "zjstream": "ZjStream",
    "hp_acl_firmware": "HP ACL 固件/初始化流",
    "escpr": "Epson ESC/P-R",
    "ufr": "Canon UFR II",
    "capt": "Canon CAPT",
    "spl": "Samsung SPL/QPDL",
    "text": "文本/RAW",
    "unknown": "未知二进制流",
}
CONVERSION_DETAILS = {
    "pdf": ("无需转换", "原始打印流已经是 PDF"),
    "postscript": ("Ghostscript", "可使用 Ghostscript 转换为 PDF"),
    "pclxl": ("GhostPCL", "可使用 GhostPCL 转换为 PDF"),
    "pcl": ("GhostPCL", "可使用 GhostPCL 转换为 PDF"),
    "zjstream": ("zjsdecode", "解压 JBIG 页面后合成为 PDF"),
    "hp_acl_firmware": ("忽略", "打印机固件或初始化数据，不属于报告页面"),
    "text": ("文本渲染", "可按文本内容生成 PDF"),
    "escpr": ("仅采集", "当前未配置 Epson ESC/P-R 转换器，请下载原始 PRN 分析"),
    "ufr": ("仅采集", "当前未配置 Canon UFR II 转换器，请下载原始 PRN 分析"),
    "capt": ("仅采集", "当前未配置 Canon CAPT 转换器，请下载原始 PRN 分析"),
    "spl": ("仅采集", "当前未配置 Samsung SPL/QPDL 转换器，请下载原始 PRN 分析"),
    "unknown": ("仅采集", "协议未知，请下载原始 PRN 进一步分析"),
}
SAMPLE_LIMIT = 256 * 1024
HEADER_PREVIEW_BYTES = 64
METADATA_LIMIT = 64 * 1024
COMPLETION_REASON_LABELS = {
    "pjl_eoj": "PJL 作业结束",
    "pjl_uel": "PJL/UEL 结束",
    "pcl_uel": "PCL UEL 结束",
    "pclxl_uel": "PCL XL UEL 结束",
    "postscript_uel": "PostScript UEL 结束",
    "postscript_ctrl_d": "PostScript Ctrl-D 结束",
    "postscript_eof": "PostScript EOF 结束",
    "pdf_eof": "PDF EOF 结束",
    "idle_timeout": "空闲超时兜底",
    "device_disconnect": "USB 断开",
    "recovered_after_restart": "重启后恢复",
}
CONVERSION_STATUS_LABELS = {
    "pending": "等待转换",
    "running": "正在转换",
    "completed": "转换完成",
    "failed": "转换失败",
    "disabled": "转换未启用",
    "ignored": "已忽略",
}


def analyze_prn(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    stat = source.stat()
    digest = hashlib.sha256()
    sample = bytearray()
    with source.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            if len(sample) < SAMPLE_LIMIT:
                sample.extend(chunk[: SAMPLE_LIMIT - len(sample)])
    data = bytes(sample)
    upper = data.upper()
    protocol = "unknown"
    confidence = "low"
    evidence = "未发现已支持协议的明确特征"

    if b"AGIACLDOWNLOAD" in upper:
        protocol, confidence, evidence = (
            "hp_acl_firmware",
            "high",
            "检测到 HP ACL 固件下载标记",
        )
    elif b"JZJZ" in data:
        protocol, confidence, evidence = "zjstream", "high", "检测到 ZjStream JZJZ 魔数"
    elif b"ENTER LANGUAGE=ACL" in upper:
        protocol, confidence, evidence = "zjstream", "medium", "PJL 指定 ACL/ZjStream"
    elif data.startswith(b"%PDF-"):
        protocol, confidence, evidence = "pdf", "high", "文件头为 %PDF-"
    elif data.startswith(b"%!") or b"%!PS-ADOBE" in upper:
        protocol, confidence, evidence = "postscript", "high", "检测到 PostScript 文件头"
    elif b"ENTER LANGUAGE=POSTSCRIPT" in upper:
        protocol, confidence, evidence = "postscript", "high", "PJL 指定 POSTSCRIPT"
    elif b" HP-PCL XL;" in upper or b"ENTER LANGUAGE=PCLXL" in upper:
        protocol, confidence, evidence = "pclxl", "high", "检测到 PCL XL 会话标记"
    elif b"ENTER LANGUAGE=PCL" in upper:
        protocol, confidence, evidence = "pcl", "high", "PJL 指定 PCL"
    elif any(marker in upper for marker in (b"ESC/P-R", b"@EJL", b"EPSON EPL")):
        protocol, confidence, evidence = "escpr", "medium", "检测到 Epson 打印流标记"
    elif any(marker in upper for marker in (b"UFRII", b"UFR II", b"CNLBP")):
        protocol, confidence, evidence = "ufr", "medium", "检测到 Canon UFR 标记"
    elif b"CAPT" in upper:
        protocol, confidence, evidence = "capt", "medium", "检测到 Canon CAPT 标记"
    elif any(marker in upper for marker in (b"QPDL", b"SPL-C", b"SPL2")):
        protocol, confidence, evidence = "spl", "medium", "检测到 Samsung SPL/QPDL 标记"
    elif any(marker in data for marker in (b"\x1bE", b"\x1b*t", b"\x1b*b")):
        protocol, confidence, evidence = "pcl", "medium", "检测到 PCL 转义命令"
    elif _looks_like_text(data):
        protocol, confidence, evidence = "text", "medium", "内容主要由可打印文本组成"

    pjl_commands = _extract_pjl_commands(data)
    language_match = re.search(rb"ENTER\s+LANGUAGE\s*=\s*([A-Z0-9_-]+)", upper)
    declared_language = language_match.group(1).decode("ascii") if language_match else ""
    converter, conversion_detail = CONVERSION_DETAILS[protocol]
    header = data[:HEADER_PREVIEW_BYTES]
    capture = _load_capture_metadata(source)
    completion_reason = str(capture.get("completion_reason", ""))
    conversion_status = str(capture.get("conversion_status", ""))

    return {
        "name": source.name,
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "modified_time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(
            timespec="seconds"
        ),
        "protocol": protocol,
        "protocol_label": PROTOCOL_LABELS[protocol],
        "confidence": confidence,
        "evidence": evidence,
        "sha256": digest.hexdigest(),
        "sampled_bytes": len(data),
        "header_hex": " ".join(f"{byte:02X}" for byte in header),
        "header_ascii": "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in header),
        "declared_language": declared_language,
        "pjl_commands": pjl_commands,
        "converter": converter,
        "conversion_detail": conversion_detail,
        "capture_metadata": bool(capture),
        "capture_protocol": str(capture.get("protocol", "")),
        "completion_reason": completion_reason,
        "completion_reason_label": COMPLETION_REASON_LABELS.get(
            completion_reason, completion_reason or "-"
        ),
        "first_byte_at": str(capture.get("first_byte_at", "")),
        "last_byte_at": str(capture.get("last_byte_at", "")),
        "boundary_detected_at": str(capture.get("boundary_detected_at", "")),
        "receive_duration_ms": _number_or_none(capture.get("receive_duration_ms")),
        "completion_duration_ms": _number_or_none(
            capture.get("completion_duration_ms")
        ),
        "received_bytes": _integer_or_none(capture.get("received_bytes")),
        "conversion_started_at": str(capture.get("conversion_started_at", "")),
        "pdf_ready_at": str(capture.get("pdf_ready_at", "")),
        "conversion_duration_ms": _number_or_none(
            capture.get("conversion_duration_ms")
        ),
        "conversion_status": conversion_status,
        "conversion_status_label": CONVERSION_STATUS_LABELS.get(
            conversion_status, conversion_status or "-"
        ),
        "conversion_error": str(capture.get("conversion_error", ""))[:1000],
        "conversion_skip_reason": str(capture.get("conversion_skip_reason", ""))[:1000],
    }


def analyze_recent_prn(directory: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    root = Path(directory)
    if not root.is_dir():
        return []
    paths = sorted(
        (path for path in root.glob("*.prn") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[: max(1, min(int(limit), 100))]
    results: list[dict[str, Any]] = []
    for path in paths:
        try:
            results.append(analyze_prn(path))
        except OSError as exc:
            results.append(
                {
                    "name": path.name,
                    "size": 0,
                    "modified_at": 0,
                    "modified_time": "",
                    "protocol": "unknown",
                    "protocol_label": PROTOCOL_LABELS["unknown"],
                    "confidence": "low",
                    "evidence": f"读取失败：{exc}",
                    "sha256": "",
                    "sampled_bytes": 0,
                    "header_hex": "",
                    "header_ascii": "",
                    "declared_language": "",
                    "pjl_commands": [],
                    "converter": "无法分析",
                    "conversion_detail": "文件读取失败",
                    "capture_metadata": False,
                    "capture_protocol": "",
                    "completion_reason": "",
                    "completion_reason_label": "-",
                    "first_byte_at": "",
                    "last_byte_at": "",
                    "boundary_detected_at": "",
                    "receive_duration_ms": None,
                    "completion_duration_ms": None,
                    "received_bytes": None,
                    "conversion_started_at": "",
                    "pdf_ready_at": "",
                    "conversion_duration_ms": None,
                    "conversion_status": "",
                    "conversion_status_label": "-",
                    "conversion_error": "",
                    "conversion_skip_reason": "",
                }
            )
    return results


def _looks_like_text(data: bytes) -> bool:
    if not data or b"\x00" in data:
        return False
    sample = data[:8192]
    printable = sum(byte in b"\t\r\n" or 32 <= byte <= 126 or byte >= 128 for byte in sample)
    return printable / len(sample) >= 0.95


def _extract_pjl_commands(data: bytes) -> list[str]:
    commands: list[str] = []
    for match in re.finditer(rb"@PJL[^\r\n]*", data, flags=re.IGNORECASE):
        value = match.group(0).decode("latin-1", errors="replace").strip()
        if value and value not in commands:
            commands.append(value[:512])
        if len(commands) >= 12:
            break
    return commands


def _load_capture_metadata(source: Path) -> dict[str, Any]:
    path = source.with_suffix(source.suffix + ".meta.json")
    try:
        if path.stat().st_size > METADATA_LIMIT:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _integer_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
