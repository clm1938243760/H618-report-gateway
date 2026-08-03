from __future__ import annotations

import asyncio
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .config import CleanupConfig, MscConfig, PdfConfig, PrinterConfig, RuntimeConfig
from .report_upload import ReportJobStore

LOGGER = logging.getLogger(__name__)


class MaintenanceManager:
    def __init__(
        self,
        config: CleanupConfig,
        runtime: RuntimeConfig,
        pdf: PdfConfig,
        printer: PrinterConfig,
        msc: MscConfig,
        store: ReportJobStore,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.pdf = pdf
        self.printer = printer
        self.msc = msc
        self.store = store
        self.command_runner = command_runner
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._lock = threading.Lock()
        self._last_run_at = 0.0
        self._next_run_at = self._scheduled_at()
        self._last_result: dict[str, Any] = {}
        self._running = False

    def update_config(
        self,
        config: CleanupConfig,
        runtime: RuntimeConfig,
        pdf: PdfConfig,
        printer: PrinterConfig,
        msc: MscConfig,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.pdf = pdf
        self.printer = printer
        self.msc = msc
        self._next_run_at = self._scheduled_at()
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "running": self._running,
            "last_run_at": self._last_run_at,
            "next_run_at": self._next_run_at if self.config.enabled else 0,
            "last_result": self._last_result,
        }

    async def run(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            if self.config.enabled and now >= self._next_run_at:
                try:
                    await asyncio.to_thread(self.cleanup_all)
                except Exception:
                    LOGGER.exception("automatic maintenance failed")
                self._next_run_at = self._scheduled_at()
            timeout = 3600.0
            if self.config.enabled:
                timeout = max(1.0, min(3600.0, self._next_run_at - time.time()))
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

    def cleanup_all(self) -> dict[str, Any]:
        with self._lock:
            self._running = True
            started = time.time()
            try:
                result = {
                    "reports": self._cleanup_reports(self.config.report_retention_days),
                    "logs": self._cleanup_logs(self.config.log_retention_days),
                }
                result["started_at"] = started
                result["finished_at"] = time.time()
                self._last_result = result
                self._last_run_at = result["finished_at"]
                return result
            finally:
                self._running = False

    def cleanup_reports(self, retention_days: int | None = None) -> dict[str, Any]:
        with self._lock:
            self._running = True
            try:
                result = self._cleanup_reports(retention_days or self.config.report_retention_days)
                self._record_manual_result("reports", result)
                return result
            finally:
                self._running = False

    def cleanup_logs(self, retention_days: int | None = None) -> dict[str, Any]:
        with self._lock:
            self._running = True
            try:
                result = self._cleanup_logs(retention_days or self.config.log_retention_days)
                self._record_manual_result("logs", result)
                return result
            finally:
                self._running = False

    def _cleanup_reports(self, retention_days: int) -> dict[str, Any]:
        cutoff = time.time() - max(1, int(retention_days)) * 86400
        pdf_root = Path(self.pdf.output_dir).resolve()
        deleted_job_ids: list[int] = []
        files_deleted = 0
        bytes_freed = 0
        skipped = 0

        for job in self.store.cleanup_candidates(cutoff):
            path = Path(str(job["pdf_path"]))
            if not _is_safe_file(path, pdf_root):
                skipped += 1
                continue
            try:
                if path.exists():
                    size = path.stat().st_size
                    path.unlink()
                    files_deleted += 1
                    bytes_freed += size
                deleted_job_ids.append(int(job["id"]))
            except OSError as exc:
                skipped += 1
                LOGGER.warning("failed to delete uploaded report %s: %s", path, exc)

        raw_deleted, raw_bytes = _delete_old_files(
            [Path(self.printer.output_dir), Path(self.msc.output_dir)],
            cutoff,
        )
        files_deleted += raw_deleted
        bytes_freed += raw_bytes
        jobs_deleted = self.store.delete_uploaded(deleted_job_ids)
        result = {
            "retention_days": int(retention_days),
            "jobs_deleted": jobs_deleted,
            "files_deleted": files_deleted,
            "bytes_freed": bytes_freed,
            "skipped": skipped,
        }
        LOGGER.info("report cleanup complete: %s", result)
        return result

    def _cleanup_logs(self, retention_days: int) -> dict[str, Any]:
        retention_days = max(1, int(retention_days))
        result = self.command_runner(
            ["journalctl", f"--vacuum-time={retention_days}d"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        log_deleted, log_bytes = _delete_old_files(
            [Path(self.runtime.data_dir) / "logs"],
            time.time() - retention_days * 86400,
        )
        payload = {
            "retention_days": retention_days,
            "files_deleted": log_deleted,
            "bytes_freed": log_bytes,
            "journal_output": (result.stdout or "")[-2000:],
        }
        LOGGER.info("log cleanup complete: %s", payload)
        return payload

    def _record_manual_result(self, kind: str, result: dict[str, Any]) -> None:
        now = time.time()
        self._last_run_at = now
        self._last_result = {kind: result, "manual": True, "finished_at": now}

    def _scheduled_at(self) -> float:
        return time.time() + max(1, int(self.config.interval_hours)) * 3600


def _is_safe_file(path: Path, root: Path) -> bool:
    if path.is_symlink():
        return False
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return not path.exists() or path.is_file()


def _delete_old_files(roots: list[Path], cutoff: float) -> tuple[int, int]:
    deleted = 0
    bytes_freed = 0
    for root in roots:
        if not root.exists():
            continue
        resolved_root = root.resolve()
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file() or not _is_safe_file(path, resolved_root):
                continue
            try:
                stat = path.stat()
                if stat.st_mtime >= cutoff:
                    continue
                path.unlink()
                deleted += 1
                bytes_freed += stat.st_size
            except OSError as exc:
                LOGGER.warning("failed to delete old file %s: %s", path, exc)
        for directory in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
    return deleted, bytes_freed
