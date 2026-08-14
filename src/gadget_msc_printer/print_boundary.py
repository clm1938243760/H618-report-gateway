from __future__ import annotations

import re
from dataclasses import dataclass


UEL = b"\x1b%-12345X"
POSTSCRIPT_EOF = b"%%EOF"
PDF_HEADER = b"%PDF-"
POSTSCRIPT_HEADER = b"%!"
BOUNDARY_GRACE_NS = 200_000_000
PROBE_LIMIT = 64 * 1024
SUPPORTED_BOUNDARY_PROTOCOLS = ("PJL", "PCL", "PCL XL", "PostScript", "PDF")


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
        self._control_tail = bytearray()
        self._raw_tail = bytearray()
        self._pcl_command: bytearray | None = None
        self._pcl_binary_remaining = 0
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
            byte = data[index]
            self.total_bytes += 1
            self.last_data_ns = now_ns
            self._append_probe(byte)

            if self._pcl_binary_remaining:
                self._pcl_binary_remaining -= 1
                self._seen_payload = True
                self._control_tail.clear()
                self._raw_tail.clear()
                index += 1
                continue

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

        # Offsets are relative to the complete feed call. segment_start is kept
        # for clarity: reset() makes each suffix a new independently probed job.
        del segment_start
        return events

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
        if self.protocol != "unknown":
            return
        probe = bytes(self._probe)
        if probe.startswith(PDF_HEADER) or (
            self.total_bytes <= 256 and probe.endswith(PDF_HEADER)
        ):
            self.protocol = "pdf"
        elif probe.startswith(POSTSCRIPT_HEADER) or (
            self.total_bytes <= 256 and probe.endswith(POSTSCRIPT_HEADER)
        ):
            self.protocol = "postscript"

    def _consume_control_byte(self, byte: int, now_ns: int) -> str:
        if self._pending and self._pending.protocol in {"pdf", "postscript"}:
            if byte == 0x04:
                reason = "postscript_ctrl_d" if self.protocol == "postscript" else "pdf_eof"
                self._pending = None
                return reason
            if byte not in b"\x00\x09\x0a\x0c\x0d\x20":
                self._pending = None

        self._raw_tail.append(byte)
        del self._raw_tail[:-32]

        self._track_pcl_command(byte)
        if self._pcl_binary_remaining:
            return ""

        self._control_tail.append(byte)
        del self._control_tail[:-128]
        tail = bytes(self._control_tail)

        if self.protocol == "pdf" and tail.endswith(POSTSCRIPT_EOF):
            self._pending = _PendingBoundary("pdf_eof", "pdf", now_ns)
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
            language_match = re.search(rb"LANGUAGE\s*=\s*([A-Z0-9_-]+)", line)
            if language_match:
                language = language_match.group(1)
                if language in {b"PCLXL", b"PCL6"}:
                    self.protocol = "pclxl"
                elif language == b"PCL":
                    self.protocol = "pcl"
                elif language in {b"POSTSCRIPT", b"PS"}:
                    self.protocol = "postscript"
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
