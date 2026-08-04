from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from .config import PdfConfig, UploadConfig
from .report_info import ReportInfoManager, ReportInfoSnapshot

LOGGER = logging.getLogger(__name__)

REPORT_STATUS_GROUPS = {
    "success": ("uploaded",),
    "failed": ("retry_wait", "exhausted"),
    "pending": ("pending", "uploading"),
}
REPORT_STATUSES = {status for values in REPORT_STATUS_GROUPS.values() for status in values}

REPORT_JOB_COLUMNS_SQL = """
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pdf_path TEXT NOT NULL,
    pdf_name TEXT NOT NULL,
    pdf_size INTEGER NOT NULL,
    pdf_sha256 TEXT NOT NULL,
    xml_content BLOB NOT NULL,
    xml_sha256 TEXT NOT NULL,
    device_code TEXT NOT NULL,
    exam_doct_code TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_attempt_at REAL NOT NULL DEFAULT 0,
    last_http_status INTEGER,
    last_error TEXT NOT NULL DEFAULT '',
    last_response TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
"""


class ReportJobStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='report_jobs'"
            ).fetchone()
            normalized = "" if schema is None else "".join(str(schema["sql"]).upper().split())
            if "UNIQUE(PDF_SHA256)" in normalized:
                connection.execute("ALTER TABLE report_jobs RENAME TO report_jobs_legacy")
                connection.execute("DROP INDEX IF EXISTS report_jobs_ready")
                connection.execute(f"CREATE TABLE report_jobs ({REPORT_JOB_COLUMNS_SQL})")
                connection.execute("INSERT INTO report_jobs SELECT * FROM report_jobs_legacy")
                connection.execute("DROP TABLE report_jobs_legacy")
                LOGGER.info("report job database migrated for configurable deduplication")
            else:
                connection.execute(f"CREATE TABLE IF NOT EXISTS report_jobs ({REPORT_JOB_COLUMNS_SQL})")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS report_jobs_ready ON report_jobs(status, next_attempt_at, id)"
            )
            connection.execute(
                "UPDATE report_jobs SET status='retry_wait', next_attempt_at=0 WHERE status='uploading'"
            )
            connection.commit()

    def enqueue(
        self,
        pdf_path: Path,
        snapshot: ReportInfoSnapshot,
        source: str,
        deduplicate: bool = True,
    ) -> int | None:
        stat = pdf_path.stat()
        digest = _sha256_file(pdf_path)
        now = time.time()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            dedupe_field = "pdf_sha256" if deduplicate else "pdf_path"
            dedupe_value = digest if deduplicate else str(pdf_path)
            existing = connection.execute(
                f"SELECT 1 FROM report_jobs WHERE {dedupe_field}=? LIMIT 1",
                (dedupe_value,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return None
            cursor = connection.execute(
                """
                INSERT INTO report_jobs (
                    pdf_path, pdf_name, pdf_size, pdf_sha256, xml_content,
                    xml_sha256, device_code, exam_doct_code, source, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    str(pdf_path), pdf_path.name, stat.st_size, digest, snapshot.content,
                    snapshot.sha256, snapshot.device_code, snapshot.exam_doct_code,
                    source, now, now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def next_ready(self, max_attempts: int) -> dict[str, Any] | None:
        now = time.time()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM report_jobs
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
                "UPDATE report_jobs SET status='uploading', attempts=?, last_attempt_at=?, updated_at=? WHERE id=?",
                (attempts, now, now, int(row["id"])),
            )
            connection.commit()
            item = dict(row)
            item["attempts"] = attempts
            return item

    def finish(
        self,
        job_id: int,
        success: bool,
        attempts: int,
        max_attempts: int,
        retry_seconds: int,
        http_status: int | None,
        error: str,
        response: str,
    ) -> None:
        now = time.time()
        if success:
            status = "uploaded"
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
                UPDATE report_jobs SET status=?, next_attempt_at=?, last_http_status=?,
                    last_error=?, last_response=?, updated_at=? WHERE id=?
                """,
                (status, next_attempt, http_status, error[:1000], response[:2000], now, job_id),
            )
            connection.commit()

    def retry(self, job_id: int) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE report_jobs SET status='pending', attempts=0, next_attempt_at=0,
                    last_error='', updated_at=? WHERE id=? AND status != 'uploaded'
                """,
                (time.time(), job_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def get(self, job_id: int) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM report_jobs WHERE id=?",
                (int(job_id),),
            ).fetchone()
        return None if row is None else dict(row)

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, pdf_path, pdf_name, pdf_size, pdf_sha256, xml_sha256,
                    device_code, exam_doct_code, source, status, attempts,
                    next_attempt_at, last_attempt_at, last_http_status,
                    last_error, last_response, created_at, updated_at
                FROM report_jobs ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_page(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str = "",
        start_at: float | None = None,
        end_at: float | None = None,
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        where: list[str] = []
        parameters: list[Any] = []

        selected_statuses: tuple[str, ...] = ()
        if status in REPORT_STATUS_GROUPS:
            selected_statuses = REPORT_STATUS_GROUPS[status]
        elif status in REPORT_STATUSES:
            selected_statuses = (status,)
        if selected_statuses:
            placeholders = ",".join("?" for _ in selected_statuses)
            where.append(f"status IN ({placeholders})")
            parameters.extend(selected_statuses)
        if start_at is not None:
            where.append("created_at >= ?")
            parameters.append(float(start_at))
        if end_at is not None:
            where.append("created_at <= ?")
            parameters.append(float(end_at))

        where_sql = " WHERE " + " AND ".join(where) if where else ""
        with closing(self._connect()) as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) AS count FROM report_jobs{where_sql}",
                    parameters,
                ).fetchone()["count"]
            )
            pages = max(1, (total + page_size - 1) // page_size)
            page = min(page, pages)
            rows = connection.execute(
                f"""
                SELECT id, pdf_path, pdf_name, pdf_size, pdf_sha256, xml_sha256,
                    device_code, exam_doct_code, source, status, attempts,
                    next_attempt_at, last_attempt_at, last_http_status,
                    last_error, last_response, created_at, updated_at
                FROM report_jobs{where_sql}
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                [*parameters, page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "jobs": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "total": total,
        }

    def cleanup_candidates(self, cutoff: float) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, pdf_path, pdf_size, status, created_at
                FROM report_jobs
                WHERE status='uploaded' AND created_at < ?
                ORDER BY id
                """,
                (float(cutoff),),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_uploaded(self, job_ids: list[int]) -> int:
        ids = sorted({int(job_id) for job_id in job_ids})
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"DELETE FROM report_jobs WHERE status='uploaded' AND id IN ({placeholders})",
                ids,
            )
            connection.commit()
            return int(cursor.rowcount)

    def counts(self) -> dict[str, int]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS count FROM report_jobs GROUP BY status").fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}


class ReportUploadWorker:
    def __init__(self, config: UploadConfig, pdf: PdfConfig, report_info: ReportInfoManager) -> None:
        self.config = config
        self.pdf = pdf
        self.report_info = report_info
        self.store = ReportJobStore(config.state_db)
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()

    def update_config(self, config: UploadConfig) -> None:
        self.config = config

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        LOGGER.info("report upload worker watching: %s", self.pdf.output_dir)
        while not self._stop.is_set():
            try:
                if self.config.enabled:
                    await asyncio.to_thread(self.scan_once)
                    await asyncio.to_thread(self.process_ready)
            except Exception:
                LOGGER.exception("report upload cycle failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(0.5, self.config.poll_interval_seconds))
            except asyncio.TimeoutError:
                pass

    def scan_once(self) -> int:
        try:
            snapshot = self.report_info.snapshot()
        except ValueError as exc:
            LOGGER.warning("report upload waiting for valid ReportInfo.xml: %s", exc)
            return 0
        root = Path(self.pdf.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        count = 0
        now = time.time()
        for path in sorted(root.rglob("*.pdf")):
            if not path.is_file() or path.name.startswith("."):
                continue
            age = now - path.stat().st_mtime
            if 0 <= age < self.config.file_stable_seconds:
                continue
            source = "msc" if "_msc_" in path.name else "printer" if "_print_" in path.name else "unknown"
            if self.store.enqueue(path, snapshot, source, self.config.deduplicate) is not None:
                if age < 0:
                    LOGGER.warning("report has future mtime; treating as stable: %s", path)
                count += 1
                LOGGER.info("report queued: %s", path)
        return count

    def process_ready(self, one_only: bool = False) -> int:
        processed = 0
        while self.config.enabled:
            job = self.store.next_ready(self.config.max_attempts)
            if job is None:
                break
            success, status, error, response = self._upload(job)
            self.store.finish(
                int(job["id"]), success, int(job["attempts"]), self.config.max_attempts,
                self.config.retry_interval_seconds, status, error, response,
            )
            processed += 1
            if success:
                LOGGER.info("report uploaded: %s", job["pdf_path"])
            else:
                LOGGER.error("report upload failed: %s error=%s", job["pdf_path"], error)
            if one_only:
                break
        return processed

    def _upload(self, job: dict[str, Any]) -> tuple[bool, int | None, str, str]:
        pdf_path = Path(str(job["pdf_path"]))
        if not pdf_path.exists():
            return False, None, "PDF file no longer exists", ""
        if _sha256_file(pdf_path) != str(job["pdf_sha256"]):
            return False, None, "PDF content changed after it was queued", ""
        boundary = "----k2b-h618-gateway-%s" % uuid.uuid4().hex
        body = _multipart_body(
            boundary,
            (
                ("Report", pdf_path.name, "application/pdf", pdf_path.read_bytes()),
                ("ReportInfo", "ReportInfo.xml", "application/xml", bytes(job["xml_content"])),
            ),
        )
        request = urllib.request.Request(
            self.config.endpoint,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
                "User-Agent": self.config.user_agent,
                "MacCode": str(job["device_code"]),
                "MsgId": uuid.uuid4().hex,
                "hospitalCode": self.config.hospital_code,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as result:
                status = int(getattr(result, "status", result.getcode()))
                response = result.read().decode("utf-8", errors="replace")
            success, error = response_is_success(status, response)
            return success, status, error, response
        except urllib.error.HTTPError as exc:
            response = exc.read().decode("utf-8", errors="replace")
            return False, int(exc.code), f"HTTP {exc.code}: {response[:500]}", response
        except Exception as exc:
            return False, None, str(exc), ""


def response_is_success(status: int, text: str) -> tuple[bool, str]:
    if not 200 <= status < 300:
        return False, f"HTTP status {status}"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return True, ""
    if not isinstance(payload, dict):
        return True, ""
    success = payload.get("success")
    code = str(payload.get("code", "")).upper()
    if success is False or code in {"FAIL", "FAILED", "ERROR"}:
        return False, f"backend rejected report: {text[:500]}"
    if code and code != "SUCCESS":
        return False, f"backend returned code {code}: {text[:500]}"
    data = payload.get("data")
    if isinstance(data, dict) and "code" in data:
        data_code = str(data.get("code", "")).upper()
        if data_code in {"100", "SUCCESS"}:
            return True, ""
        if data_code in {"201", "202", "203", "204", "205", "FAIL", "FAILED", "ERROR"}:
            return False, f"backend returned data.code {data_code}: {text[:500]}"
    if success is True or code == "SUCCESS":
        return True, ""
    return True, ""


def _multipart_body(boundary: str, files: tuple[tuple[str, str, str, bytes], ...]) -> bytes:
    chunks: list[bytes] = []
    marker = boundary.encode("ascii")
    for field, filename, content_type, content in files:
        chunks.extend(
            [
                b"--" + marker + b"\r\n",
                f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
                content,
                b"\r\n",
            ]
        )
    chunks.append(b"--" + marker + b"--\r\n")
    return b"".join(chunks)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
