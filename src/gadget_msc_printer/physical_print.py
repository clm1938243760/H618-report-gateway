from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .config import PdfConfig, PhysicalPrinterConfig
from .cups_manager import CupsManager

LOGGER = logging.getLogger(__name__)


class PhysicalPrintStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS physical_print_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pdf_path TEXT NOT NULL,
                    pdf_sha256 TEXT NOT NULL,
                    queue_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    cups_job_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(pdf_path, pdf_sha256)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS physical_print_ready ON physical_print_jobs(status, next_attempt_at, id)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS physical_print_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "UPDATE physical_print_jobs SET status='retry_wait', next_attempt_at=0 WHERE status='submitting'"
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def is_initialized(self) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM physical_print_meta WHERE key='baseline_initialized'"
            ).fetchone()
        return row is not None and row["value"] == "1"

    def mark_initialized(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO physical_print_meta(key, value) VALUES('baseline_initialized', '1')"
            )
            connection.commit()

    def known_paths(self) -> set[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT DISTINCT pdf_path FROM physical_print_jobs").fetchall()
        return {str(row["pdf_path"]) for row in rows}

    def add(self, path: Path, queue_name: str, status: str = "pending") -> bool:
        now = time.time()
        digest = _sha256_file(path)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO physical_print_jobs (
                    pdf_path, pdf_sha256, queue_name, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(path), digest, queue_name, status, now, now),
            )
            connection.commit()
            return cursor.rowcount > 0

    def next_ready(self, max_attempts: int) -> dict[str, Any] | None:
        now = time.time()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM physical_print_jobs
                WHERE status IN ('pending', 'retry_wait')
                  AND next_attempt_at <= ? AND attempts < ?
                ORDER BY id LIMIT 1
                """,
                (now, max_attempts),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            attempts = int(row["attempts"]) + 1
            connection.execute(
                "UPDATE physical_print_jobs SET status='submitting', attempts=?, updated_at=? WHERE id=?",
                (attempts, now, int(row["id"])),
            )
            connection.commit()
            result = dict(row)
            result["attempts"] = attempts
            return result

    def finish(
        self,
        job_id: int,
        success: bool,
        attempts: int,
        max_attempts: int,
        retry_seconds: int,
        error: str = "",
        cups_job_id: str = "",
    ) -> None:
        now = time.time()
        if success:
            status = "submitted"
            next_attempt = 0.0
        elif attempts >= max_attempts:
            status = "exhausted"
            next_attempt = 0.0
        else:
            status = "retry_wait"
            next_attempt = now + retry_seconds
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE physical_print_jobs
                SET status=?, next_attempt_at=?, last_error=?, cups_job_id=?, updated_at=?
                WHERE id=?
                """,
                (status, next_attempt, error[:1000], cups_job_id[:256], now, int(job_id)),
            )
            connection.commit()

    def counts(self) -> dict[str, int]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM physical_print_jobs GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, pdf_path, queue_name, status, attempts, last_error,
                    cups_job_id, created_at, updated_at
                FROM physical_print_jobs ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(int(limit), 50)),),
            ).fetchall()
        return [dict(row) for row in rows]


class PhysicalPrintWorker:
    def __init__(
        self,
        config: PhysicalPrinterConfig,
        pdf: PdfConfig,
        cups: CupsManager,
    ) -> None:
        self.config = config
        self.pdf = pdf
        self.cups = cups
        self.store = PhysicalPrintStore(config.state_db)
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()

    def update_config(self, config: PhysicalPrinterConfig) -> None:
        self.config = config
        if Path(config.state_db) != self.store.db_path:
            self.store = PhysicalPrintStore(config.state_db)

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def initialize_baseline(self) -> int:
        if self.store.is_initialized():
            return 0
        root = Path(self.pdf.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        count = 0
        for path in sorted(root.rglob("*.pdf")):
            if path.is_file() and not path.name.startswith("."):
                count += int(self.store.add(path, self.config.queue_name, status="baseline"))
        self.store.mark_initialized()
        LOGGER.info("physical print baseline initialized with %s existing PDF files", count)
        return count

    def scan_once(self) -> int:
        self.initialize_baseline()
        if not self.config.enabled or not self.config.auto_print:
            return 0
        root = Path(self.pdf.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        count = 0
        now = time.time()
        known_paths = self.store.known_paths()
        for path in sorted(root.rglob("*.pdf")):
            if not path.is_file() or path.name.startswith("."):
                continue
            path_key = str(path)
            if path_key in known_paths:
                continue
            age = now - path.stat().st_mtime
            if 0 <= age < self.config.file_stable_seconds:
                continue
            if self.store.add(path, self.config.queue_name):
                count += 1
                known_paths.add(path_key)
                LOGGER.info("physical print queued: %s", path)
        return count

    def process_ready(self, one_only: bool = False) -> int:
        if not self.config.enabled or not self.config.auto_print:
            return 0
        processed = 0
        while True:
            job = self.store.next_ready(self.config.max_attempts)
            if job is None:
                break
            path = Path(str(job["pdf_path"]))
            success = False
            error = ""
            cups_job_id = ""
            try:
                if not path.is_file():
                    raise FileNotFoundError("PDF file no longer exists")
                if _sha256_file(path) != str(job["pdf_sha256"]):
                    raise ValueError("PDF content changed after it was queued")
                cups_job_id = self.cups.print_file(path, self.config)
                success = True
            except Exception as exc:
                error = str(exc)
                LOGGER.error("physical print failed: %s error=%s", path, error)
            self.store.finish(
                int(job["id"]),
                success,
                int(job["attempts"]),
                self.config.max_attempts,
                self.config.retry_interval_seconds,
                error,
                cups_job_id,
            )
            processed += 1
            if one_only:
                break
        return processed

    def status(self) -> dict[str, Any]:
        return {"counts": self.store.counts(), "recent": self.store.recent()}

    async def run(self) -> None:
        await asyncio.to_thread(self.initialize_baseline)
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.scan_once)
                await asyncio.to_thread(self.process_ready)
            except Exception:
                LOGGER.exception("physical print cycle failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=max(0.5, self.config.poll_interval_seconds)
                )
            except asyncio.TimeoutError:
                pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
