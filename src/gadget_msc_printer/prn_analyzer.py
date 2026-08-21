from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .document_formats import (
    declared_pjl_language,
    detect_escp2_profile_hint,
    detect_c_printer_protocol,
    detect_epson_protocol,
    detect_image_format,
    detect_modern_print_format,
    detect_xps_package,
    looks_like_hpgl,
    looks_like_pcl3gui,
)
from .private_raster import detect_private_raster, private_raster_dpi, private_raster_spec


PROTOCOL_LABELS = {
    "pdf": "PDF",
    "postscript": "PostScript",
    "pclxl": "PCL XL",
    "pcl": "PCL",
    "pcl3gui": "PCL3/PCL3GUI",
    "hpgl": "HP-GL/2",
    "xps": "XPS",
    "oxps": "OpenXPS",
    "zjstream": "ZjStream",
    "xqx": "HP XQX",
    "hiperc": "OKI HIPERC",
    "hbpl": "HBPL",
    "ddst": "Ricoh DDST",
    "lavaflow": "LAVAFLOW",
    "opl": "Raster Object/OPL",
    "slx": "Lexmark SLX",
    "oakt": "Oak Technology OAKT",
    "gipd": "Granite GIPD",
    "brother_hbp": "Brother HBP/XL2HB",
    "jpeg": "JPEG图像",
    "png": "PNG图像",
    "bmp": "BMP图像",
    "tiff": "TIFF图像",
    "pcx": "PCX图像",
    "dcx": "DCX多页图像",
    "pwg_raster": "PWG Raster",
    "cups_raster": "CUPS Raster",
    "pclm": "PCLm",
    "apple_urf": "Apple URF",
    "hp_acl_firmware": "HP ACL 固件/初始化流",
    "escp": "Epson ESC/P",
    "escp2": "Epson ESC/P2",
    "escpr": "Epson ESC/P-R",
    "escpage": "Epson ESC/Page",
    "epson": "Epson 未确定打印流",
    "ufr": "Canon UFR II",
    "capt": "Canon CAPT",
    "pantum_gdi": "Pantum GDI",
    "sharp_splc": "Sharp SPLC",
    "ricoh_rpcs": "Ricoh RPCS",
    "ibm_afp": "IBM AFP",
    "zpl": "Zebra ZPL",
    "epl": "Zebra EPL",
    "cpcl": "Zebra CPCL",
    "printrex": "Printrex",
    "spl": "Samsung SPL/QPDL",
    "text": "文本/RAW",
    "unknown": "未知二进制流",
}
CONVERSION_DETAILS = {
    "pdf": ("无需转换", "原始打印流已经是 PDF"),
    "postscript": ("Ghostscript", "可使用 Ghostscript 转换为 PDF"),
    "pclxl": ("GhostPCL", "可使用 GhostPCL 转换为 PDF"),
    "pcl": ("GhostPCL", "可使用 GhostPCL 转换为 PDF"),
    "pcl3gui": (
        "C组：仅识别",
        "完整编码链和修正版GhostPCL均无法正确还原页面；保留原始PRN供分析和下载",
    ),
    "hpgl": ("GhostPCL", "可使用 GhostPCL 转换 HP-GL/2 为 PDF"),
    "xps": ("xpstopdf/GhostXPS", "可使用本地 XPS 解析器转换为 PDF"),
    "oxps": ("xpstopdf/GhostXPS", "可使用本地 XPS 解析器转换为 PDF"),
    "zjstream": ("zjsdecode", "解压 JBIG 页面后合成为 PDF"),
    "xqx": ("xqxdecode", "解压 XQX 页面后合成为 PDF"),
    "hiperc": ("hipercdecode", "解压 HIPERC 页面后合成为 PDF"),
    "hbpl": ("审核版 hbpldecode", "使用隔离安装的审核版解码器生成页面后合成为 PDF"),
    "ddst": ("审核版 ddstdecode", "使用隔离安装的审核版解码器生成页面后合成为 PDF"),
    "lavaflow": ("lavadecode", "解压 LAVAFLOW 页面后合成为 PDF"),
    "opl": ("审核版 opldecode", "使用隔离安装的审核版解码器生成页面后合成为 PDF"),
    "slx": ("审核版 slxdecode", "使用隔离安装的审核版解码器生成页面后合成为 PDF"),
    "oakt": ("oakdecode", "解压 OAKT 页面和灰度子平面后合成为 PDF"),
    "gipd": (
        "仅采集",
        "Noble gipddecode 只能分析GDIJ/GDIP/GDIB结构，不能导出页面；保留原始PRN",
    ),
    "brother_hbp": ("审核版 brdecode", "解压 Brother HBP/XL2HB 页面后合成为 PDF"),
    "jpeg": ("Pillow", "可将JPEG图像转换为PDF"),
    "png": ("Pillow", "可将PNG图像转换为PDF"),
    "bmp": ("Pillow", "可将BMP图像转换为PDF"),
    "tiff": ("Pillow", "可将单页或多页TIFF转换为PDF"),
    "pcx": ("Pillow", "可将PCX图像转换为PDF"),
    "dcx": ("Pillow", "可将DCX中的全部PCX页面转换为PDF"),
    "pwg_raster": (
        "pwgtopdf",
        "使用板端固定的CUPS pwgtopdf过滤器离线转换为PDF",
    ),
    "cups_raster": (
        "pwgtopdf",
        "使用板端固定的CUPS pwgtopdf过滤器离线转换为PDF",
    ),
    "pclm": ("直接保留PDF", "PCLm是PDF-based打印流，直接保留其PDF内容"),
    "apple_urf": (
        "pwgtopdf",
        "使用板端固定的CUPS pwgtopdf过滤器离线转换为PDF",
    ),
    "hp_acl_firmware": ("忽略", "打印机固件或初始化数据，不属于报告页面"),
    "text": ("文本渲染", "可按文本内容生成 PDF"),
    "escp": ("EscaPy", "v0.81研发包离线安装EscaPy后可转换为PDF"),
    "escp2": ("EscaPy", "v0.81研发包离线安装EscaPy后可转换为PDF"),
    "escpr": (
        "内置ESC/P-R解码器",
        "支持Epson printer-driver-escpr 1.7.17生成的COLOR、MONO和多页RGB光栅；其他ESC/P-R变体失败时保留原始PRN",
    ),
    "escpage": ("仅采集", "当前没有配置Epson ESC/Page反向转换器"),
    "epson": ("仅采集", "仅检测到Epson/EJL外层标记，无法安全确定内部打印语言"),
    "ufr": ("仅采集", "当前未配置 Canon UFR II 转换器，请下载原始 PRN 分析"),
    "capt": ("仅采集", "当前未配置 Canon CAPT 转换器，请下载原始 PRN 分析"),
    "pantum_gdi": (
        "C组：仅识别",
        "检测到明确的 Pantum GDI 标记；当前不执行私有 GDI 反向转换，保留原始PRN",
    ),
    "sharp_splc": (
        "C组：仅识别",
        "检测到 Sharp 厂商上下文和 SPLC 标记；当前不执行私有 SPLC 反向转换，保留原始PRN",
    ),
    "ricoh_rpcs": (
        "C组：仅识别",
        "检测到 Ricoh RPCS 标记；当前不执行私有 RPCS 反向转换，保留原始PRN",
    ),
    "ibm_afp": (
        "C组：仅识别",
        "检测到连续 AFP 结构化字段；当前不执行 AFP 反向转换，保留原始PRN",
    ),
    "zpl": (
        "C组：仅识别",
        "检测到 Zebra ZPL 标签命令；当前不转换，保留原始PRN供分析和下载",
    ),
    "epl": (
        "C组：仅识别",
        "检测到 Zebra EPL 标签命令；当前不转换，保留原始PRN供分析和下载",
    ),
    "cpcl": (
        "C组：仅识别",
        "检测到 Zebra CPCL 标签命令；当前不转换，保留原始PRN供分析和下载",
    ),
    "printrex": (
        "C组：仅识别",
        "检测到 Printrex 明确标记；当前不执行专用反向转换，保留原始PRN",
    ),
    "spl": ("qpdldecode", "解压 QPDL/SPL-C 页面后合成为 PDF"),
    "unknown": ("仅采集", "协议未知，请下载原始 PRN 进一步分析"),
}
C_GROUP_CAPABILITIES = (
    {
        "id": "C01",
        "protocols": "PCL3 / PCL3GUI",
        "label": "HP主机型喷墨打印流",
        "models": "HP DeskJet 2130 / 2330等",
        "evidence": "PJL明确声明PCL3、PCL3GUI或PCLGUI",
    },
    {
        "id": "C02",
        "protocols": "Canon UFR II / UFR II LT",
        "label": "Canon UFR打印流",
        "models": "Canon MF3010、LBP212dw、imageRUNNER等",
        "evidence": "UFR语言声明或明确UFR II标记",
    },
    {
        "id": "C03",
        "protocols": "Canon CAPT",
        "label": "Canon CAPT主机打印流",
        "models": "Canon LBP2900 / 3000等",
        "evidence": "CAPT语言声明或明确CAPT标记",
    },
    {
        "id": "C04",
        "protocols": "Pantum GDI",
        "label": "奔图主机打印流",
        "models": "Pantum P2200、P2500、M6500等",
        "evidence": "Pantum厂商信息与GDI上下文同时出现",
    },
    {
        "id": "C05",
        "protocols": "Sharp SPLC",
        "label": "Sharp SPLC打印流",
        "models": "Sharp采用SPLC的机型（以实际驱动为准）",
        "evidence": "Sharp厂商上下文与SPLC标记同时出现",
    },
    {
        "id": "C06",
        "protocols": "Ricoh RPCS",
        "label": "Ricoh RPCS打印流",
        "models": "Ricoh Aficio及采用RPCS驱动的机型",
        "evidence": "RPCS语言声明，或Ricoh与RPCS标记同时出现",
    },
    {
        "id": "C07",
        "protocols": "Granite GIPD",
        "label": "Granite GDI打印流",
        "models": "Lexmark X500、Dell 1125MFP等",
        "evidence": "检测到GDIJ、GDIP或GDIB结构标记",
    },
    {
        "id": "C08",
        "protocols": "IBM AFP",
        "label": "AFP结构化打印流",
        "models": "IBM InfoPrint及大型机AFP任务",
        "evidence": "检测到连续有效AFP结构化字段",
    },
    {
        "id": "C09",
        "protocols": "Epson ESC/Page",
        "label": "Epson激光打印语言",
        "models": "Epson AcuLaser部分机型",
        "evidence": "PJL或EJL明确声明ESC/Page",
    },
    {
        "id": "C10",
        "protocols": "Zebra ZPL / EPL / CPCL",
        "label": "Zebra标签打印语言",
        "models": "Zebra ZD/ZT、GK/GX及移动标签机",
        "evidence": "检测到对应作业头与成组标签命令",
    },
    {
        "id": "C11",
        "protocols": "Printrex",
        "label": "Printrex医疗热敏打印流",
        "models": "Printrex医疗和工业热敏打印机",
        "evidence": "检测到明确Printrex协议或厂商标记",
    },
)
C_GROUP_PROTOCOL_IDS = frozenset(
    {
        "pcl3gui",
        "ufr",
        "capt",
        "pantum_gdi",
        "sharp_splc",
        "ricoh_rpcs",
        "gipd",
        "ibm_afp",
        "escpage",
        "zpl",
        "epl",
        "cpcl",
        "printrex",
    }
)
SAMPLE_LIMIT = 256 * 1024
HEADER_PREVIEW_BYTES = 64
METADATA_LIMIT = 64 * 1024
COMPLETION_REASON_LABELS = {
    "pjl_eoj": "PJL 作业结束",
    "pjl_uel": "PJL/UEL 结束",
    "pcl_uel": "PCL UEL 结束",
    "pclxl_uel": "PCL XL UEL 结束",
    "hpgl_uel": "HP-GL/2 UEL 结束",
    "postscript_uel": "PostScript UEL 结束",
    "postscript_ctrl_d": "PostScript Ctrl-D 结束",
    "postscript_eof": "PostScript EOF 结束",
    "pdf_eof": "PDF EOF 结束",
    "pclm_eof": "PCLm EOF 结束",
    "escpr_endj": "ESC/P-R EndJob 结束",
    "idle_timeout": "空闲超时兜底",
    "device_disconnect": "USB 断开",
    "recovered_after_restart": "重启后恢复",
}
CONVERSION_STATUS_LABELS = {
    "pending": "等待转换",
    "running": "正在转换",
    "completed": "转换完成",
    "failed": "转换失败",
    "retained": "仅识别，已保留",
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
    modern_protocol = detect_modern_print_format(data)
    protocol = "unknown"
    confidence = "low"
    evidence = "未发现已支持协议的明确特征"

    if b"AGIACLDOWNLOAD" in upper:
        protocol, confidence, evidence = (
            "hp_acl_firmware",
            "high",
            "检测到 HP ACL 固件下载标记",
        )
    elif modern_protocol == "pclm":
        protocol, confidence, evidence = (
            "pclm",
            "high",
            "检测到PDF文件头和PCLm标记",
        )
    elif data.startswith(b"%PDF-"):
        protocol, confidence, evidence = "pdf", "high", "文件头为 %PDF-"
    elif modern_protocol == "pwg_raster":
        protocol, confidence, evidence = (
            "pwg_raster",
            "high",
            "检测到PWG Raster魔数RaS2PwgRaster",
        )
    elif modern_protocol == "cups_raster":
        protocol, confidence, evidence = (
            "cups_raster",
            "high",
            "检测到CUPS Raster同步字RaSt/RaS2/RaS3或反字节序形式",
        )
    elif modern_protocol == "apple_urf":
        protocol, confidence, evidence = (
            "apple_urf",
            "high",
            "检测到Apple URF魔数UNIRAST",
        )
    elif image_format := detect_image_format(data):
        protocol, confidence, evidence = (
            image_format,
            "high",
            f"检测到 {image_format.upper()} 图像文件头",
        )
    elif xps_protocol := detect_xps_package(source):
        protocol, confidence, evidence = (
            xps_protocol,
            "high",
            "检测到固定文档序列和固定页面的 OPC 包结构",
        )
    elif data.startswith(b"%!") or b"%!PS-ADOBE" in upper:
        protocol, confidence, evidence = "postscript", "high", "检测到 PostScript 文件头"
    elif b"ENTER LANGUAGE=POSTSCRIPT" in upper:
        protocol, confidence, evidence = "postscript", "high", "PJL 指定 POSTSCRIPT"
    elif c_protocol := detect_c_printer_protocol(data):
        c_evidence = {
            "ufr": "检测到 Canon UFR/UFR II 标记",
            "capt": "检测到 Canon CAPT 标记",
            "pantum_gdi": "检测到 Pantum/GDI 标记",
            "sharp_splc": "检测到 Sharp 厂商上下文和 SPLC 标记",
            "ricoh_rpcs": "检测到 Ricoh RPCS 标记",
            "ibm_afp": "检测到连续 AFP 结构化字段",
            "zpl": "检测到 ZPL ^XA、字段命令组合",
            "epl": "检测到 EPL N/A/B/P 命令组合",
            "cpcl": "检测到 CPCL 作业头、文本/图形命令和 PRINT",
            "printrex": "检测到 Printrex 协议标记",
        }
        protocol, confidence, evidence = c_protocol, "high", c_evidence[c_protocol]
    elif private_raster := detect_private_raster(data):
        protocol, confidence, evidence = (
            private_raster.protocol,
            "high",
            private_raster.evidence,
        )
    elif looks_like_pcl3gui(data):
        protocol, confidence, evidence = (
            "pcl3gui",
            "high",
            "PJL声明PCL3/PCL3GUI打印语言",
        )
    elif b" HP-PCL XL;" in upper or declared_pjl_language(data) in {"PCLXL", "PCL6"}:
        protocol, confidence, evidence = "pclxl", "high", "检测到 PCL XL 会话标记"
    elif declared_pjl_language(data) == "PCL":
        protocol, confidence, evidence = "pcl", "high", "PJL 指定 PCL"
    elif looks_like_hpgl(data):
        protocol, confidence, evidence = "hpgl", "high", "检测到 HP-GL/2 模式或绘图命令序列"
    elif epson_protocol := detect_epson_protocol(data):
        evidence_by_protocol = {
            "escp": "检测到经典ESC/P初始化和打印命令序列",
            "escp2": "检测到ESC/P2扩展定位或栅格命令序列",
            "escpr": "检测到Epson ESC/P-R明确标记",
            "escpage": "检测到Epson ESC/Page明确标记",
            "epson": "检测到Epson EJL外层标记，但内部语言不明确",
        }
        protocol, confidence, evidence = (
            epson_protocol,
            "high" if epson_protocol != "epson" else "medium",
            evidence_by_protocol[epson_protocol],
        )
    elif any(marker in upper for marker in (b"UFRII", b"UFR II", b"CNLBP")):
        protocol, confidence, evidence = "ufr", "medium", "检测到 Canon UFR 标记"
    elif b"CAPT" in upper:
        protocol, confidence, evidence = "capt", "medium", "检测到 Canon CAPT 标记"
    elif any(marker in data for marker in (b"\x1bE", b"\x1b*t", b"\x1b*b")):
        protocol, confidence, evidence = "pcl", "medium", "检测到 PCL 转义命令"
    elif _looks_like_text(data):
        protocol, confidence, evidence = "text", "medium", "内容主要由可打印文本组成"

    pjl_commands = _extract_pjl_commands(data)
    declared_language = declared_pjl_language(data)
    converter, conversion_detail = CONVERSION_DETAILS[protocol]
    raster_spec = private_raster_spec(protocol)
    if raster_spec and not raster_spec.enabled:
        converter = "仅采集"
        conversion_detail = raster_spec.disabled_reason
    raster_dpi = private_raster_dpi(data, protocol) if raster_spec else None
    header = data[:HEADER_PREVIEW_BYTES]
    capture = _load_capture_metadata(source)
    completion_reason = str(capture.get("completion_reason", ""))
    conversion_status = str(capture.get("conversion_status", ""))
    conversion_error = str(capture.get("conversion_error", ""))[:1000]
    conversion_skip_reason = str(capture.get("conversion_skip_reason", ""))[:1000]
    escp2_profile_hint, escp2_profile_evidence = (
        detect_escp2_profile_hint(data) if protocol == "escp2" else (None, "")
    )
    if protocol in C_GROUP_PROTOCOL_IDS and conversion_status == "failed":
        conversion_status = "retained"
        conversion_skip_reason = conversion_skip_reason or conversion_error or conversion_detail
        conversion_error = ""

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
        "raster_dpi_x": raster_dpi[0] if raster_dpi else None,
        "raster_dpi_y": raster_dpi[1] if raster_dpi else None,
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
        "conversion_error": conversion_error,
        "conversion_skip_reason": conversion_skip_reason,
        "escp2_profile_hint": escp2_profile_hint or "",
        "escp2_profile_evidence": escp2_profile_evidence,
        "escp2_profile_used": str(capture.get("escp2_profile_used", "")),
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
                    "raster_dpi_x": None,
                    "raster_dpi_y": None,
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
                    "escp2_profile_hint": "",
                    "escp2_profile_evidence": "",
                    "escp2_profile_used": "",
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
