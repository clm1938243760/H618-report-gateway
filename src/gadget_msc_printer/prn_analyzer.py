from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROTOCOL_LABELS = {
    "pdf": "PDF",
    "postscript": "PostScript",
    "pclxl": "PCL XL",
    "pcl": "PCL",
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
    "text": ("文本渲染", "可按文本内容生成 PDF"),
    "escpr": ("仅采集", "当前未配置 Epson ESC/P-R 转换器，请下载原始 PRN 分析"),
    "ufr": ("仅采集", "当前未配置 Canon UFR II 转换器，请下载原始 PRN 分析"),
    "capt": ("仅采集", "当前未配置 Canon CAPT 转换器，请下载原始 PRN 分析"),
    "spl": ("仅采集", "当前未配置 Samsung SPL/QPDL 转换器，请下载原始 PRN 分析"),
    "unknown": ("仅采集", "协议未知，请下载原始 PRN 进一步分析"),
}
SAMPLE_LIMIT = 256 * 1024
HEADER_PREVIEW_BYTES = 64


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

    if data.startswith(b"%PDF-"):
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
