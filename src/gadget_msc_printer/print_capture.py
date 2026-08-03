from __future__ import annotations

import asyncio
import errno
import logging
import os
import select
import time
from datetime import datetime
from pathlib import Path

from .config import PrinterConfig
from .pdf_converter import PdfConverter

LOGGER = logging.getLogger(__name__)


class PrintCapture:
    def __init__(self, config: PrinterConfig, converter: PdfConverter | None = None) -> None:
        self.config = config
        self.converter = converter
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._stop = asyncio.Event()
        self._last_wait_log: float | None = None

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        if not self.config.enabled:
            LOGGER.info("printer capture disabled")
            return
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

    def _capture_once(self) -> None:
        LOGGER.debug("opening printer device: %s", self.config.device)
        fd = os.open(self.config.device, os.O_RDONLY | os.O_NONBLOCK)
        poller = select.poll()
        poller.register(fd, select.POLLIN)
        current: Path | None = None
        handle = None
        total = 0
        last_data = 0.0
        try:
            while not self._stop.is_set():
                events = poller.poll(100)
                data = b""
                if events:
                    try:
                        data = os.read(fd, self.config.chunk_size)
                    except BlockingIOError:
                        data = b""
                now = time.monotonic()
                if data:
                    if handle is None:
                        current = self._new_job_path()
                        handle = current.open("wb")
                        total = 0
                        LOGGER.info("print job start: %s", current)
                    handle.write(data)
                    handle.flush()
                    total += len(data)
                    last_data = now
                    continue
                if handle is not None and now - last_data >= self.config.idle_complete_seconds:
                    handle.close()
                    handle = None
                    assert current is not None
                    if total >= self.config.min_job_bytes:
                        LOGGER.info("print job saved: %s bytes=%d", current, total)
                        if self.converter:
                            self.converter.convert(current, "print")
                    else:
                        LOGGER.warning("print job too small, remove: %s bytes=%d", current, total)
                        current.unlink(missing_ok=True)
                    current = None
                    total = 0
        finally:
            if handle is not None:
                handle.close()
            os.close(fd)

    def _new_job_path(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return self.output_dir / f"print_{stamp}.prn"

    def _log_waiting(self, message: str, *args: object) -> None:
        now = time.monotonic()
        if self._last_wait_log is not None and now - self._last_wait_log < 60.0:
            return
        self._last_wait_log = now
        LOGGER.warning(message, *args)
