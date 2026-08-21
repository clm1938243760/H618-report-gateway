from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import queue
import select
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from .config import PrinterConfig
from .pdf_converter import PdfConverter
from .print_boundary import BoundaryEvent, PrintBoundaryDetector

LOGGER = logging.getLogger(__name__)
METADATA_SCHEMA_VERSION = 2


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class _ActiveJob:
    final_path: Path
    part_path: Path
    handle: BinaryIO
    first_byte_ns: int
    first_byte_at: datetime
    last_byte_ns: int
    last_byte_at: datetime
    total: int = 0


class PrintCapture:
    def __init__(self, config: PrinterConfig, converter: PdfConverter | None = None) -> None:
        self.config = config
        self.converter = converter
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._stop = threading.Event()
        self._last_wait_log: float | None = None
        self._conversion_queue: queue.Queue[Path | None] = queue.Queue()
        self._converter_thread: threading.Thread | None = None
        self._metadata_lock = threading.Lock()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        if not self.config.enabled:
            LOGGER.info("printer capture disabled")
            return
        await asyncio.to_thread(self._recover_pending_jobs)
        self._start_converter_worker()
        try:
            while not self._stop.is_set():
                if not Path(self.config.device).exists():
                    self._log_waiting("waiting for printer device: %s", self.config.device)
                    await asyncio.sleep(2)
                    continue
                try:
                    await asyncio.to_thread(self._capture_once)
                except OSError as exc:
                    if exc.errno in {errno.ENODEV, errno.ENXIO}:
                        self._log_waiting("printer host disconnected; waiting for reconnect")
                    else:
                        LOGGER.exception("printer capture failed")
                    await asyncio.sleep(2)
                except Exception:
                    LOGGER.exception("printer capture failed")
                    await asyncio.sleep(2)
        finally:
            self._stop.set()
            self._conversion_queue.put(None)
            if self._converter_thread and self._converter_thread.is_alive():
                await asyncio.to_thread(self._converter_thread.join, 10.0)

    def _capture_once(self) -> None:
        LOGGER.debug("opening printer device: %s", self.config.device)
        fd = os.open(self.config.device, os.O_RDONLY | os.O_NONBLOCK)
        poller = select.poll()
        poller.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP | select.POLLNVAL)
        detector = PrintBoundaryDetector()
        active: _ActiveJob | None = None
        idle_timeout_ns = int(self.config.idle_complete_seconds * 1_000_000_000)
        try:
            while not self._stop.is_set():
                events = poller.poll(100)
                now_ns = time.monotonic_ns()
                now_at = _utc_now()
                data = b""
                if events:
                    event_mask = events[0][1]
                    if event_mask & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                        if active is not None:
                            self._complete_job(
                                active,
                                BoundaryEvent(0, detector.protocol, "device_disconnect"),
                                now_ns,
                                now_at,
                            )
                            active = None
                            detector.reset()
                        raise OSError(errno.ENODEV, "printer host disconnected")
                    try:
                        data = os.read(fd, self.config.chunk_size)
                    except BlockingIOError:
                        data = b""

                if data:
                    boundaries = detector.feed(data, now_ns)
                    cursor = 0
                    for boundary in boundaries:
                        if boundary.end_offset < cursor or boundary.end_offset > len(data):
                            raise RuntimeError("print boundary detector returned an invalid offset")
                        chunk = data[cursor : boundary.end_offset]
                        if chunk:
                            active = self._write_chunk(active, chunk, now_ns, now_at)
                        if active is not None:
                            self._complete_job(active, boundary, now_ns, now_at)
                            active = None
                        cursor = boundary.end_offset
                    remaining = data[cursor:]
                    if remaining:
                        active = self._write_chunk(active, remaining, now_ns, now_at)
                    continue

                boundary = detector.poll(now_ns, idle_timeout_ns)
                if boundary is not None and active is not None:
                    self._complete_job(active, boundary, now_ns, now_at)
                    active = None
                    detector.reset()
        finally:
            if active is not None:
                self._close_part(active)
                LOGGER.info(
                    "print capture stopped with partial job retained: %s bytes=%d",
                    active.part_path,
                    active.total,
                )
            os.close(fd)

    def _write_chunk(
        self,
        active: _ActiveJob | None,
        data: bytes,
        now_ns: int,
        now_at: datetime,
    ) -> _ActiveJob:
        if active is None:
            final_path = self._new_job_path()
            part_path = final_path.with_suffix(final_path.suffix + ".part")
            active = _ActiveJob(
                final_path=final_path,
                part_path=part_path,
                handle=part_path.open("wb"),
                first_byte_ns=now_ns,
                first_byte_at=now_at,
                last_byte_ns=now_ns,
                last_byte_at=now_at,
            )
            LOGGER.info("print job start: %s", final_path)
        active.handle.write(data)
        active.total += len(data)
        active.last_byte_ns = now_ns
        active.last_byte_at = now_at
        return active

    def _complete_job(
        self,
        active: _ActiveJob,
        boundary: BoundaryEvent,
        completed_ns: int,
        completed_at: datetime,
    ) -> None:
        self._close_part(active, sync=True)
        if active.total < self.config.min_job_bytes:
            LOGGER.warning(
                "print job too small, remove: %s bytes=%d reason=%s",
                active.part_path,
                active.total,
                boundary.reason,
            )
            active.part_path.unlink(missing_ok=True)
            return

        os.replace(active.part_path, active.final_path)
        metadata = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "protocol": boundary.protocol or "unknown",
            "completion_reason": boundary.reason,
            "first_byte_at": _iso_utc(active.first_byte_at),
            "last_byte_at": _iso_utc(active.last_byte_at),
            "boundary_detected_at": _iso_utc(completed_at),
            "receive_duration_ms": round(
                max(0, active.last_byte_ns - active.first_byte_ns) / 1_000_000,
                3,
            ),
            "completion_duration_ms": round(
                max(0, completed_ns - active.first_byte_ns) / 1_000_000,
                3,
            ),
            "received_bytes": active.total,
            "conversion_started_at": "",
            "pdf_ready_at": "",
            "conversion_duration_ms": None,
            "conversion_status": "pending" if self.converter else "disabled",
            "pdf_path": "",
            "conversion_error": "",
            "conversion_skip_reason": "",
            "escp2_profile_used": "",
        }
        self._write_metadata(active.final_path, metadata)
        LOGGER.info(
            "print job saved: %s bytes=%d protocol=%s reason=%s receive_ms=%.3f",
            active.final_path,
            active.total,
            metadata["protocol"],
            boundary.reason,
            metadata["receive_duration_ms"],
        )
        if self.converter:
            self._conversion_queue.put(active.final_path)

    def _close_part(self, active: _ActiveJob, sync: bool = False) -> None:
        if active.handle.closed:
            return
        try:
            active.handle.flush()
            if sync:
                os.fsync(active.handle.fileno())
        finally:
            active.handle.close()

    def _start_converter_worker(self) -> None:
        if self.converter is None or (self._converter_thread and self._converter_thread.is_alive()):
            return
        self._converter_thread = threading.Thread(
            target=self._conversion_loop,
            name="printer-pdf-converter",
            daemon=True,
        )
        self._converter_thread.start()

    def _conversion_loop(self) -> None:
        while True:
            source = self._conversion_queue.get()
            try:
                if source is None:
                    return
                try:
                    self._convert_job(source)
                except Exception:
                    LOGGER.exception("unhandled asynchronous conversion error: %s", source)
            finally:
                self._conversion_queue.task_done()

    def _convert_job(self, source: Path) -> None:
        if self.converter is None or not source.is_file():
            return
        metadata = self._read_metadata(source) or {}
        ignore_reason = getattr(self.converter, "ignore_reason", None)
        skip_reason = ignore_reason(source) if callable(ignore_reason) else ""
        if skip_reason:
            metadata["conversion_status"] = "ignored"
            metadata["conversion_error"] = ""
            metadata["conversion_skip_reason"] = skip_reason
            metadata["conversion_duration_ms"] = 0.0
            self._write_metadata(source, metadata)
            LOGGER.info("print stream ignored: %s reason=%s", source, skip_reason)
            return
        started_ns = time.monotonic_ns()
        metadata["conversion_started_at"] = _iso_utc(_utc_now())
        metadata["conversion_status"] = "running"
        metadata["conversion_error"] = ""
        metadata["conversion_skip_reason"] = ""
        self._write_metadata(source, metadata)
        try:
            target = self.converter.convert(source, "print")
            metadata["escp2_profile_used"] = str(
                getattr(self.converter, "last_escp2_profile", "")
            )
            metadata["conversion_duration_ms"] = round(
                max(0, time.monotonic_ns() - started_ns) / 1_000_000,
                3,
            )
            if target is None:
                outcome = str(getattr(self.converter, "last_outcome", ""))
                detail = str(
                    getattr(self.converter, "last_error", "") or "converter returned no PDF"
                )[:1000]
                if outcome in {"disabled", "ignored", "retained"}:
                    metadata["conversion_status"] = outcome
                    metadata["conversion_error"] = ""
                    metadata["conversion_skip_reason"] = detail
                else:
                    metadata["conversion_status"] = "failed"
                    metadata["conversion_error"] = detail
            else:
                metadata["conversion_status"] = "completed"
                metadata["pdf_ready_at"] = _iso_utc(_utc_now())
                metadata["pdf_path"] = str(target)
        except Exception as exc:
            metadata["conversion_duration_ms"] = round(
                max(0, time.monotonic_ns() - started_ns) / 1_000_000,
                3,
            )
            metadata["conversion_status"] = "failed"
            metadata["conversion_error"] = str(exc)[:1000]
            LOGGER.exception("asynchronous print conversion failed: %s", source)
        finally:
            self._write_metadata(source, metadata)

    def _recover_pending_jobs(self) -> None:
        queued: set[Path] = set()
        for part_path in sorted(self.output_dir.glob("*.prn.part")):
            try:
                size = part_path.stat().st_size
                if size < self.config.min_job_bytes:
                    part_path.unlink(missing_ok=True)
                    continue
                final_path = part_path.with_suffix("")
                if final_path.exists():
                    LOGGER.warning("partial print job conflicts with completed file: %s", part_path)
                    continue
                os.replace(part_path, final_path)
                now = _utc_now()
                metadata = {
                    "schema_version": METADATA_SCHEMA_VERSION,
                    "protocol": "unknown",
                    "completion_reason": "recovered_after_restart",
                    "first_byte_at": datetime.fromtimestamp(
                        final_path.stat().st_mtime, timezone.utc
                    ).isoformat(timespec="milliseconds"),
                    "last_byte_at": datetime.fromtimestamp(
                        final_path.stat().st_mtime, timezone.utc
                    ).isoformat(timespec="milliseconds"),
                    "boundary_detected_at": _iso_utc(now),
                    "receive_duration_ms": None,
                    "completion_duration_ms": None,
                    "received_bytes": size,
                    "conversion_started_at": "",
                    "pdf_ready_at": "",
                    "conversion_duration_ms": None,
                    "conversion_status": "pending" if self.converter else "disabled",
                    "pdf_path": "",
                    "conversion_error": "",
                    "conversion_skip_reason": "",
                    "escp2_profile_used": "",
                }
                self._write_metadata(final_path, metadata)
                if self.converter:
                    self._conversion_queue.put(final_path)
                    queued.add(final_path)
                LOGGER.warning("recovered partial print job after restart: %s", final_path)
            except OSError:
                LOGGER.exception("failed to recover partial print job: %s", part_path)

        if self.converter:
            for source in sorted(self.output_dir.glob("*.prn")):
                if source in queued:
                    continue
                metadata = self._read_metadata(source)
                if metadata and metadata.get("conversion_status") in {"pending", "running"}:
                    metadata["conversion_status"] = "pending"
                    self._write_metadata(source, metadata)
                    self._conversion_queue.put(source)

    def _metadata_path(self, source: Path) -> Path:
        return source.with_suffix(source.suffix + ".meta.json")

    def _read_metadata(self, source: Path) -> dict[str, Any] | None:
        with self._metadata_lock:
            try:
                value = json.loads(self._metadata_path(source).read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else None
            except (OSError, ValueError, TypeError):
                return None

    def _write_metadata(self, source: Path, metadata: dict[str, Any]) -> None:
        target = self._metadata_path(source)
        temp = target.with_suffix(target.suffix + ".tmp")
        payload = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with self._metadata_lock:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)

    def _new_job_path(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return self.output_dir / f"print_{stamp}.prn"

    def _log_waiting(self, message: str, *args: object) -> None:
        now = time.monotonic()
        if self._last_wait_log is not None and now - self._last_wait_log < 60.0:
            return
        self._last_wait_log = now
        LOGGER.warning(message, *args)
