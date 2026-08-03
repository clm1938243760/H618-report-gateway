from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gadget_msc_printer.config import DeviceConfig, PdfConfig, UploadConfig
from gadget_msc_printer.report_info import ReportInfoManager
from gadget_msc_printer.report_upload import ReportUploadWorker, response_is_success


class _UploadHandler(BaseHTTPRequestHandler):
    response_payload = {"success": True, "code": "SUCCESS"}
    received = b""
    received_headers: dict[str, str] = {}

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        type(self).received = self.rfile.read(length)
        type(self).received_headers = {
            "MacCode": self.headers.get("MacCode", ""),
            "MsgId": self.headers.get("MsgId", ""),
            "hospitalCode": self.headers.get("hospitalCode", ""),
        }
        payload = json.dumps(type(self).response_payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return


class ReportUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        _UploadHandler.received = b""
        _UploadHandler.received_headers = {}
        _UploadHandler.response_payload = {"success": True, "code": "SUCCESS"}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _UploadHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _worker(self, directory: str) -> ReportUploadWorker:
        root = Path(directory)
        reports = root / "reports"
        reports.mkdir()
        info = ReportInfoManager(DeviceConfig(report_info_path=str(root / "ReportInfo.xml")))
        info.write("D-001", "测试医生", "DOC-009")
        upload = UploadConfig(
            endpoint=f"http://127.0.0.1:{self.server.server_port}/upload",
            state_db=str(root / "jobs.sqlite3"),
            file_stable_seconds=0,
            retry_interval_seconds=1,
            max_attempts=3,
        )
        return ReportUploadWorker(upload, PdfConfig(output_dir=str(reports)), info)

    def test_uploads_pdf_and_minimal_xml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = self._worker(directory)
            (Path(directory) / "reports" / "report_msc_1.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
            self.assertEqual(worker.scan_once(), 1)
            self.assertEqual(worker.process_ready(), 1)
            jobs = worker.store.list_recent()
        self.assertEqual(jobs[0]["status"], "uploaded")
        self.assertIn(b'name="Report"', _UploadHandler.received)
        self.assertIn(b'name="ReportInfo"', _UploadHandler.received)
        self.assertIn(b"<DeviceCode>D-001</DeviceCode>", _UploadHandler.received)
        self.assertNotIn(b"xmlns", _UploadHandler.received)
        self.assertEqual(_UploadHandler.received_headers.get("MacCode"), "D-001")
        self.assertEqual(_UploadHandler.received_headers.get("hospitalCode"), "tejian01")
        self.assertRegex(_UploadHandler.received_headers.get("MsgId", ""), r"^[0-9a-f]{32}$")

    def test_failed_job_retries_instead_of_being_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = self._worker(directory)
            (Path(directory) / "reports" / "report_print_1.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
            _UploadHandler.response_payload = {"success": False, "code": "FAIL"}
            worker.scan_once()
            worker.process_ready(one_only=True)
            failed = worker.store.list_recent()[0]
            self.assertEqual(failed["status"], "retry_wait")
            self.assertEqual(failed["attempts"], 1)
            worker.store.retry(int(failed["id"]))
            _UploadHandler.response_payload = {"success": True, "code": "SUCCESS"}
            worker.process_ready(one_only=True)
            uploaded = worker.store.list_recent()[0]
        self.assertEqual(uploaded["status"], "uploaded")

    def test_config_change_does_not_requeue_historical_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = self._worker(directory)
            report = Path(directory) / "reports" / "historical.pdf"
            report.write_bytes(b"%PDF-1.4\nold-report\n%%EOF\n")
            self.assertEqual(worker.scan_once(), 1)
            worker.report_info.write("D-CHANGED", "变更医生", "DOC-CHANGED")
            self.assertEqual(worker.scan_once(), 0)
            jobs = worker.store.list_recent()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["device_code"], "D-001")

    def test_deduplication_can_be_disabled_for_repeated_test_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = self._worker(directory)
            worker.config.deduplicate = False
            first = Path(directory) / "reports" / "first_msc_report.pdf"
            second = Path(directory) / "reports" / "second_msc_report.pdf"
            content = b"%PDF-1.4\nsame-test-content\n%%EOF\n"
            first.write_bytes(content)
            second.write_bytes(content)

            self.assertEqual(worker.scan_once(), 2)
            self.assertEqual(worker.scan_once(), 0)

            jobs = worker.store.list_recent()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["pdf_sha256"], jobs[1]["pdf_sha256"])

    def test_future_fat_timestamp_does_not_block_queueing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = self._worker(directory)
            worker.config.file_stable_seconds = 2
            report = Path(directory) / "reports" / "future_msc_report.pdf"
            report.write_bytes(b"%PDF-1.4\nfuture-time\n%%EOF\n")
            future = time.time() + 8 * 60 * 60
            os.utime(report, (future, future))

            with self.assertLogs("gadget_msc_printer.report_upload", level="WARNING") as logs:
                self.assertEqual(worker.scan_once(), 1)
                self.assertEqual(worker.scan_once(), 0)

            jobs = worker.store.list_recent()
        self.assertEqual(jobs[0]["status"], "pending")
        future_warnings = [line for line in logs.output if "future mtime" in line]
        self.assertEqual(len(future_warnings), 1)

    def test_report_store_pages_and_filters_by_status_and_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = self._worker(directory)
            worker.config.deduplicate = False
            snapshot = worker.report_info.snapshot()
            reports = Path(directory) / "reports"
            ids: list[int] = []
            for index in range(25):
                report = reports / f"report_{index:02d}.pdf"
                report.write_bytes(f"report-{index}".encode("ascii"))
                job_id = worker.store.enqueue(report, snapshot, "msc", deduplicate=False)
                self.assertIsNotNone(job_id)
                ids.append(int(job_id))
                if index % 2 == 0:
                    worker.store.finish(int(job_id), True, 1, 3, 60, 200, "", "ok")

            old = time.time() - 10 * 86400
            with closing(worker.store._connect()) as connection:
                connection.execute(
                    "UPDATE report_jobs SET created_at=?, updated_at=? WHERE id=?",
                    (old, old, ids[0]),
                )
                connection.commit()

            second_page = worker.store.list_page(page=2, page_size=10)
            success = worker.store.list_page(page_size=100, status="success")
            recent = worker.store.list_page(page_size=100, start_at=time.time() - 86400)

        self.assertEqual(second_page["total"], 25)
        self.assertEqual(second_page["pages"], 3)
        self.assertEqual(len(second_page["jobs"]), 10)
        self.assertEqual(success["total"], 13)
        self.assertEqual(recent["total"], 24)

    def test_response_rules_match_existing_gateway(self) -> None:
        self.assertEqual(response_is_success(200, "not-json"), (True, ""))
        self.assertTrue(response_is_success(200, '{"data":{"code":100}}')[0])
        self.assertFalse(response_is_success(200, '{"data":{"code":203}}')[0])
        self.assertFalse(response_is_success(500, "error")[0])


if __name__ == "__main__":
    unittest.main()
