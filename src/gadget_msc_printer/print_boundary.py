from __future__ import annotations

import re
from dataclasses import dataclass

from .document_formats import (
    detect_c_printer_protocol,
    detect_epson_protocol,
    detect_modern_print_format,
    looks_like_hpgl,
)
from .private_raster import detect_private_raster, private_protocol_from_pjl


UEL = b"\x1b%-12345X"
POSTSCRIPT_EOF = b"%%EOF"
PDF_HEADER = b"%PDF-"
POSTSCRIPT_HEADER = b"%!"
ESCPR_REMOTE_END_TRAILER = (
    b"\x1b@\x1b(R\x08\x00\x00REMOTE1JE\x01\x00\x00\x1b\x00\x00\x00"
)
BOUNDARY_GRACE_NS = 200_000_000
PROBE_LIMIT = 256 * 1024
ESCPR_MAX_COMMAND_PAYLOAD = 16 * 1024 * 1024
PROBE_START_CHECKPOINTS = frozenset((1, 2, 4, 8, 16, 32, 64, 128, 256))
CONTROL_BYTE_PATTERN = re.compile(rb"[\x04\x1b%@]")
PAGE_CONTROL_BYTE_PATTERN = re.compile(rb"[\x04\x1b%]")
ESCAPE_BYTE_PATTERN = re.compile(rb"\x1b")
CONTROL_MARKERS = (UEL, POSTSCRIPT_EOF, PDF_HEADER, POSTSCRIPT_HEADER)
SUPPORTED_BOUNDARY_PROTOCOLS = (
    "PJL",
    "PCL",
    "PCL XL",
    "HP-GL/2",
    "PostScript",
    "PDF",
    "PCLm",
    "CUPS Raster",
    "PWG Raster",
    "Apple URF",
    "ESC/P-R",
    "ZjStream",
    "QPDL/SPL-C",
    "XQX",
    "HIPERC",
    "HBPL",
    "DDST",
    "LAVAFLOW",
    "Raster Object/OPL",
    "SLX",
    "OAKT",
    "GIPD",
    "Brother HBP/XL2HB",
    "Canon UFR II",
    "Canon CAPT",
    "Pantum GDI",
    "Sharp SPLC",
    "Ricoh RPCS",
    "IBM AFP",
    "Zebra ZPL",
    "Zebra EPL",
    "Zebra CPCL",
    "Printrex",
)


@dataclass(frozen=True)
class BoundaryEvent:
    """A complete print job ending inside the latest feed call."""

    end_offset: int
    protocol: str
    reason: str


@dataclass
class _PendingBoundary:
    reason: str
    protocol: str
    detected_ns: int


class PrintBoundaryDetector:
    """Incrementally recognize common printer job boundaries.

    The detector intentionally stays conservative. Explicit PJL/PCL terminators
    are accepted immediately, while ambiguous PostScript/PDF markers require a
    short quiet period. Unknown and vendor-private streams are left to the
    caller's idle timeout.
    """

    def __init__(self, grace_ns: int = BOUNDARY_GRACE_NS) -> None:
        self.grace_ns = max(0, int(grace_ns))
        self.reset()

    def reset(self) -> None:
        self.protocol = "unknown"
        self.total_bytes = 0
        self.last_data_ns = 0
        self._probe = bytearray()
        self._probe_checked_size = 0
        self._probe_bulk_dirty = False
        self._control_tail = bytearray()
        self._raw_tail = bytearray()
        self._pcl_command: bytearray | None = None
        self._pcl_binary_remaining = 0
        self._escpr_header: bytearray | None = None
        self._escpr_payload_remaining = 0
        self._escpr_saw_setup = False
        self._escpr_page_open = False
        self._escpr_completed_pages = 0
        self._escpr_endj_seen = False
        self._escpr_trailer = bytearray()
        self._escpr_trailer_matches = True
        self._seen_payload = False
        self._initial_uel = False
        self._pjl_mode = False
        self._pjl_line = bytearray()
        self._saw_pjl_job = False
        self._saw_pjl_eoj = False
        self._pending: _PendingBoundary | None = None

    @property
    def has_data(self) -> bool:
        return self.total_bytes > 0

    @property
    def pending_reason(self) -> str:
        return self._pending.reason if self._pending else ""

    def feed(self, data: bytes, now_ns: int) -> list[BoundaryEvent]:
        if not data:
            return []
        events: list[BoundaryEvent] = []
        segment_start = 0
        index = 0
        while index < len(data):
            if self._escpr_payload_remaining:
                length = min(self._escpr_payload_remaining, len(data) - index)
                self._consume_escpr_payload_span(data[index : index + length], now_ns)
                self._escpr_payload_remaining -= length
                index += length
                continue

            if self._pcl_binary_remaining:
                length = min(self._pcl_binary_remaining, len(data) - index)
                self._consume_pcl_binary_span(data[index : index + length], now_ns)
                self._pcl_binary_remaining -= length
                index += length
                continue

            if self._can_fast_forward():
                match = self._next_control_match(data, index)
                end = match.start() if match else len(data)
                if end > index:
                    self._consume_opaque_span(data[index:end], now_ns)
                    index = end
                    continue

            if self._probe_bulk_dirty and self._starts_control_marker(data, index):
                self._refresh_protocol_from_probe()
            byte = data[index]
            self.total_bytes += 1
            self.last_data_ns = now_ns
            self._append_probe(byte)

            immediate_reason = self._consume_control_byte(byte, now_ns)
            if immediate_reason:
                events.append(
                    BoundaryEvent(
                        end_offset=index + 1,
                        protocol=self.protocol,
                        reason=immediate_reason,
                    )
                )
                self.reset()
                segment_start = index + 1
            index += 1

        # Check the final bytes from this USB read even when the sample has not
        # reached the next periodic scan boundary.
        self._refresh_protocol_from_probe()
        # Offsets are relative to the complete feed call. segment_start is kept
        # for clarity: reset() makes each suffix a new independently probed job.
        del segment_start
        return events

    @staticmethod
    def _starts_control_marker(data: bytes, index: int) -> bool:
        byte = data[index]
        if byte == 0x1B:
            markers = (UEL,)
        elif byte == ord("%"):
            markers = (POSTSCRIPT_EOF, PDF_HEADER, POSTSCRIPT_HEADER)
        else:
            return False
        for marker in markers:
            fragment = data[index : index + len(marker)]
            if marker.startswith(fragment):
                return True
        return False

    def _next_control_match(self, data: bytes, index: int) -> re.Match[bytes] | None:
        if self.protocol in {"pdf", "pclm", "postscript"}:
            return PAGE_CONTROL_BYTE_PATTERN.search(data, index)
        if self.protocol != "unknown":
            return ESCAPE_BYTE_PATTERN.search(data, index)
        return CONTROL_BYTE_PATTERN.search(data, index)

    def _can_fast_forward(self) -> bool:
        if (
            self._pcl_command is not None
            or self._pjl_mode
            or self._pending is not None
            or self._escpr_header is not None
            or self._escpr_endj_seen
        ):
            return False
        tail = bytes(self._control_tail)
        for marker in CONTROL_MARKERS:
            for length in range(1, len(marker)):
                if tail.endswith(marker[:length]):
                    return False
        return True

    def _extend_probe(self, data: bytes) -> None:
        remaining = PROBE_LIMIT - len(self._probe)
        if remaining > 0:
            appended = data[:remaining]
            self._probe.extend(appended)
            self._probe_bulk_dirty = bool(appended)

    def _consume_opaque_span(self, data: bytes, now_ns: int) -> None:
        if not data:
            return
        self.total_bytes += len(data)
        self.last_data_ns = now_ns
        self._extend_probe(data)
        self._raw_tail.extend(data[-32:])
        del self._raw_tail[:-32]
        self._control_tail.extend(data[-128:])
        del self._control_tail[:-128]
        if data.strip(b"\x00\x09\x0a\x0d\x20"):
            self._seen_payload = True

    def _consume_pcl_binary_span(self, data: bytes, now_ns: int) -> None:
        if not data:
            return
        self.total_bytes += len(data)
        self.last_data_ns = now_ns
        self._extend_probe(data)
        self._seen_payload = True
        self._control_tail.clear()
        self._raw_tail.clear()

    def _consume_escpr_payload_span(self, data: bytes, now_ns: int) -> None:
        if not data:
            return
        self.total_bytes += len(data)
        self.last_data_ns = now_ns
        self._extend_probe(data)
        self._seen_payload = True
        self._control_tail.clear()
        self._raw_tail.clear()

    def poll(self, now_ns: int, idle_timeout_ns: int) -> BoundaryEvent | None:
        if not self.has_data:
            return None
        if self._pending and now_ns - self._pending.detected_ns >= self.grace_ns:
            return BoundaryEvent(
                end_offset=0,
                protocol=self._pending.protocol,
                reason=self._pending.reason,
            )
        if self.last_data_ns and now_ns - self.last_data_ns >= max(0, idle_timeout_ns):
            return BoundaryEvent(
                end_offset=0,
                protocol=self.protocol,
                reason="idle_timeout",
            )
        return None

    def _append_probe(self, byte: int) -> None:
        if len(self._probe) < PROBE_LIMIT:
            self._probe.append(byte)
        size = len(self._probe)
        header_ended = (
            size <= 256
            and (
                self._probe[-len(PDF_HEADER) :] == PDF_HEADER
                or self._probe[-len(POSTSCRIPT_HEADER) :] == POSTSCRIPT_HEADER
            )
        )
        if size in PROBE_START_CHECKPOINTS or header_ended:
            self._refresh_protocol_from_probe()

    def _refresh_protocol_from_probe(self) -> None:
        if not self._probe or self._probe_checked_size == len(self._probe):
            return
        self._probe_checked_size = len(self._probe)
        self._probe_bulk_dirty = False
        probe = bytes(self._probe)
        upper = probe.upper()
        if b"AGIACLDOWNLOAD" in upper:
            self.protocol = "hp_acl_firmware"
            return
        modern_protocol = detect_modern_print_format(probe)
        if modern_protocol:
            self.protocol = modern_protocol
            return
        c_protocol = detect_c_printer_protocol(probe)
        if c_protocol:
            self.protocol = c_protocol
            return
        private_raster = detect_private_raster(probe)
        if private_raster:
            self.protocol = private_raster.protocol
            return
        epson_protocol = detect_epson_protocol(probe)
        if epson_protocol and epson_protocol != "epson":
            self.protocol = epson_protocol
            return
        if self.protocol != "unknown":
            return
        elif probe.startswith(PDF_HEADER) or (
            self.total_bytes <= 256 and probe.endswith(PDF_HEADER)
        ):
            self.protocol = "pdf"
        elif probe.startswith(POSTSCRIPT_HEADER) or (
            self.total_bytes <= 256 and probe.endswith(POSTSCRIPT_HEADER)
        ):
            self.protocol = "postscript"
        elif (
            b"ENTER LANGUAGE=HPGL" in upper
            or b"ENTER LANGUAGE=HP-GL" in upper
            or b"\x1b%0B" in probe
            or looks_like_hpgl(probe)
        ):
            self.protocol = "hpgl"

    def _consume_control_byte(self, byte: int, now_ns: int) -> str:
        if self._pending and self._pending.protocol in {"pdf", "pclm", "postscript"}:
            if byte == 0x04:
                reason = (
                    "postscript_ctrl_d"
                    if self.protocol == "postscript"
                    else "pclm_eof"
                    if self.protocol == "pclm"
                    else "pdf_eof"
                )
                self._pending = None
                return reason
            if byte not in b"\x00\x09\x0a\x0c\x0d\x20":
                self._pending = None
        if self._pending and self._pending.reason == "pjl_uel":
            pjl_continuation = self._pjl_mode and (
                bool(self._pjl_line) or byte == ord("@")
            )
            if byte not in b"\x00\x09\x0a\x0c\x0d\x20" and not pjl_continuation:
                self._pending = None

        self._raw_tail.append(byte)
        del self._raw_tail[:-32]

        if self.protocol == "escpr":
            self._pcl_command = None
            reason = self._track_escpr_command(byte, now_ns)
            self._seen_payload = True
            if reason:
                return reason
        else:
            self._track_pcl_command(byte)
        if self._pcl_binary_remaining:
            return ""

        self._control_tail.append(byte)
        del self._control_tail[:-128]
        tail = bytes(self._control_tail)

        if self.protocol in {"pdf", "pclm"} and tail.endswith(POSTSCRIPT_EOF):
            reason = "pclm_eof" if self.protocol == "pclm" else "pdf_eof"
            self._pending = _PendingBoundary(reason, self.protocol, now_ns)
        elif self.protocol == "postscript":
            if byte == 0x04 and self.total_bytes > 1:
                self._pending = None
                return "postscript_ctrl_d"
            if tail.endswith(POSTSCRIPT_EOF):
                self._pending = _PendingBoundary("postscript_eof", "postscript", now_ns)

        if tail.endswith(UEL):
            return self._handle_uel(now_ns, tail)

        self._consume_pjl_byte(byte, now_ns)
        self._update_protocol_from_tail(tail)
        if self._is_payload_byte(byte):
            self._seen_payload = True
        return ""

    def _handle_uel(self, now_ns: int, tail: bytes) -> str:
        at_job_start = self.total_bytes == len(UEL) and not self._seen_payload
        if at_job_start:
            self._initial_uel = True
            self._pjl_mode = True
            self._pjl_line.clear()
            self._pending = None
            return ""

        if self._saw_pjl_eoj:
            self._pending = None
            return "pjl_eoj"

        if self._saw_pjl_job:
            # UEL first exits the selected page description language. A PJL EOJ
            # and final UEL may follow, so retain a short fallback candidate.
            self._pjl_mode = True
            self._pjl_line.clear()
            self._pending = _PendingBoundary("pjl_uel", self.protocol, now_ns)
            return ""

        terminal_pcl = (
            tail.endswith(b"\x1bE" + UEL)
            or tail.endswith(b"\x0c\x1bE" + UEL)
            or tail.endswith(b"\x1b*rB\x0c\x1bE" + UEL)
            or tail.endswith(b"\x1b*rC\x0c\x1bE" + UEL)
        )
        if self._seen_payload and (terminal_pcl or self.protocol in {"pcl", "pclxl"}):
            self._pending = None
            return "pcl_uel" if self.protocol != "pclxl" else "pclxl_uel"
        if self._seen_payload and self.protocol == "postscript":
            self._pending = None
            return "postscript_uel"
        if self._seen_payload and self.protocol == "hpgl":
            self._pending = None
            return "hpgl_uel"
        return ""

    def _consume_pjl_byte(self, byte: int, now_ns: int) -> None:
        if not self._pjl_mode:
            return
        if not self._pjl_line and byte in b"\x09\x0a\x0d\x20":
            return
        if not self._pjl_line and byte != ord("@"):
            self._pjl_mode = False
            return
        if len(self._pjl_line) < 2048:
            self._pjl_line.append(byte)
        if byte not in (0x0A, 0x0D):
            return

        line = bytes(self._pjl_line).strip().upper()
        self._pjl_line.clear()
        if not line.startswith(b"@PJL"):
            return
        if re.search(rb"\bJOB(?:\s|$)", line):
            self._saw_pjl_job = True
        if b"ENTER" in line and b"LANGUAGE" in line:
            language_match = re.search(rb"LANGUAGE\s*=\s*([A-Z0-9_./-]+)", line)
            if language_match:
                language = language_match.group(1)
                if language in {b"PCLXL", b"PCL6"}:
                    self.protocol = "pclxl"
                elif language == b"PCL":
                    self.protocol = "pcl"
                elif language in {b"PCL3", b"PCL3GUI", b"PCLGUI"}:
                    self.protocol = "pcl3gui"
                elif language in {b"POSTSCRIPT", b"PS"}:
                    self.protocol = "postscript"
                elif language in {b"HPGL", b"HPGL2", b"HP-GL", b"HP-GL2"}:
                    self.protocol = "hpgl"
                elif language in {b"ESC/P", b"ESCP"}:
                    self.protocol = "escp"
                elif language in {b"ESC/P2", b"ESCP2"}:
                    self.protocol = "escp2"
                elif language in {b"ESC/P-R", b"ESCP-R", b"ESCPR"}:
                    self.protocol = "escpr"
                elif language in {b"ESC/PAGE", b"ESCPAGE"}:
                    self.protocol = "escpage"
                elif private_protocol := private_protocol_from_pjl(language):
                    self.protocol = private_protocol
            self._pjl_mode = False
            self._seen_payload = True
        if re.search(rb"\bEOJ(?:\s|$)", line):
            self._saw_pjl_eoj = True
            self._pending = _PendingBoundary("pjl_eoj", self.protocol, now_ns)

    def _track_pcl_command(self, byte: int) -> None:
        if self._pcl_command is None:
            if byte == 0x1B:
                self._pcl_command = bytearray([byte])
            return

        self._pcl_command.append(byte)
        if len(self._pcl_command) > 64:
            self._pcl_command = None
            return
        if not 0x40 <= byte <= 0x5E:
            return

        command = bytes(self._pcl_command)
        self._pcl_command = None
        if command == UEL:
            return
        if command == b"\x1b%0B":
            self.protocol = "hpgl"
            return
        if self.protocol == "unknown" and (
            command == b"\x1bE"
            or command.startswith(b"\x1b*b")
            or command.startswith(b"\x1b*r")
            or command.startswith(b"\x1b*t")
        ):
            self.protocol = "pcl"

        payload_match = re.search(rb"([+-]?\d+)([VW])$", command)
        if not payload_match and command.startswith(b"\x1b&p"):
            payload_match = re.search(rb"([+-]?\d+)X$", command)
        if payload_match:
            self._pcl_binary_remaining = max(0, int(payload_match.group(1)))
            self._control_tail.clear()

    def _track_escpr_command(self, byte: int, now_ns: int) -> str:
        if self._escpr_endj_seen:
            self._escpr_trailer.append(byte)
            if self._escpr_trailer_matches and not ESCPR_REMOTE_END_TRAILER.startswith(
                self._escpr_trailer
            ):
                self._escpr_trailer_matches = False
            if (
                self._escpr_trailer_matches
                and bytes(self._escpr_trailer) == ESCPR_REMOTE_END_TRAILER
            ):
                self._pending = None
                return "escpr_endj"
            return ""

        if self._escpr_header is None:
            if byte == 0x1B:
                self._escpr_header = bytearray((byte,))
            return ""

        self._escpr_header.append(byte)
        if len(self._escpr_header) < 10:
            return ""

        header = bytes(self._escpr_header)
        self._escpr_header = None
        parameter_size = int.from_bytes(header[2:6], "little")
        command_name = header[6:10]
        expected_classes = {
            b"setq": ord("q"),
            b"setj": ord("j"),
            b"sttp": ord("p"),
            b"setn": ord("n"),
            b"dsnd": ord("d"),
            b"endp": ord("p"),
            b"endj": ord("j"),
        }
        if (
            header[0] != 0x1B
            or expected_classes.get(command_name) != header[1]
            or parameter_size > ESCPR_MAX_COMMAND_PAYLOAD
        ):
            next_escape = header.rfind(b"\x1b", 1)
            if next_escape >= 0:
                self._escpr_header = bytearray(header[next_escape:])
            return ""

        self._escpr_payload_remaining = parameter_size
        if command_name in {b"setq", b"setj"}:
            self._escpr_saw_setup = True
        elif command_name == b"sttp" and self._escpr_saw_setup and parameter_size == 0:
            self._escpr_page_open = True
        elif command_name == b"endp" and self._escpr_page_open:
            self._escpr_page_open = False
            self._escpr_completed_pages += 1
        elif (
            command_name == b"endj"
            and parameter_size == 0
            and self._escpr_saw_setup
            and not self._escpr_page_open
            and self._escpr_completed_pages > 0
        ):
            self._escpr_endj_seen = True
            self._escpr_trailer.clear()
            self._escpr_trailer_matches = True
            self._pending = _PendingBoundary("escpr_endj", "escpr", now_ns)
        return ""

    def _update_protocol_from_tail(self, tail: bytes) -> None:
        upper = tail.upper()
        if b" HP-PCL XL;" in upper:
            self.protocol = "pclxl"
        elif self.protocol == "unknown" and any(
            marker in tail for marker in (b"\x1bE", b"\x1b*t", b"\x1b*b", b"\x1b*r")
        ):
            self.protocol = "pcl"

    def _is_payload_byte(self, byte: int) -> bool:
        if self.total_bytes <= len(UEL) and bytes(self._probe) == UEL[: self.total_bytes]:
            return False
        if self._pjl_mode:
            return False
        return byte not in b"\x00\x09\x0a\x0d\x20"
