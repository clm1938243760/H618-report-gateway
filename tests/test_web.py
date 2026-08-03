from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess

from aiohttp.test_utils import TestClient, TestServer

from gadget_msc_printer.auth import SessionStore
from gadget_msc_printer.config import AppConfig, save_config
from gadget_msc_printer.maintenance import MaintenanceManager
from gadget_msc_printer.report_info import ReportInfoManager
from gadget_msc_printer.report_upload import ReportUploadWorker
from gadget_msc_printer.web import ConfigWebApp


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config_path = root / "config.yaml"
        config = AppConfig()
        config.runtime.data_dir = str(root / "data")
        config.web.username = "tejian01"
        config.web.password = "test-password-123"
        config.web.static_dir = str(root / "frontend")
        config.device.device_code = "D-OLD"
        config.device.exam_doct = "旧医生"
        config.device.exam_doct_code = "DOC-OLD"
        config.device.report_info_path = str(root / "data" / "device" / "ReportInfo.xml")
        config.upload.state_db = str(root / "data" / "state" / "jobs.sqlite3")
        config.pdf.output_dir = str(root / "data" / "reports_pdf")
        config.printer.output_dir = str(root / "data" / "print_jobs")
        config.msc.output_dir = str(root / "data" / "msc_files")
        frontend = Path(config.web.static_dir)
        (frontend / "static-resource" / "js").mkdir(parents=True)
        (frontend / "index.html").write_text(
            "<!doctype html><html><body><div id=\"app\">Vue gateway</div></body></html>",
            encoding="utf-8",
        )
        (frontend / "favicon.ico").write_bytes(b"ico")
        (frontend / "static-resource" / "js" / "app.js").write_text(
            "console.log('gateway')",
            encoding="utf-8",
        )
        save_config(self.config_path, config)
        report_info = ReportInfoManager(config.device)
        report_info.write(config.device.device_code, config.device.exam_doct, config.device.exam_doct_code)
        uploader = ReportUploadWorker(config.upload, config.pdf, report_info)
        self.uploader = uploader
        self.maintenance = MaintenanceManager(
            config.cleanup,
            config.runtime,
            config.pdf,
            config.printer,
            config.msc,
            uploader.store,
            command_runner=lambda *args, **kwargs: CompletedProcess(args[0], 0, "vacuumed", ""),
        )
        self.web = ConfigWebApp(
            self.config_path,
            config,
            SessionStore(8),
            report_info,
            uploader,
            self.maintenance,
        )
        self.client = TestClient(TestServer(self.web.app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.temp.cleanup()

    async def _login(self) -> tuple[str, str]:
        response = await self.client.post(
            "/api/login",
            json={"username": "tejian01", "password": "test-password-123"},
        )
        payload = await response.json()
        self.assertEqual(response.status, 200)
        token = response.cookies["gmp_session"].value
        return token, str(payload["csrf"])

    async def test_api_requires_login(self) -> None:
        response = await self.client.get("/api/config")
        self.assertEqual(response.status, 401)

    async def test_login_session_restore_and_static_frontend(self) -> None:
        response = await self.client.post(
            "/api/login",
            json={"username": "tejian01", "password": "wrong-password"},
        )
        self.assertEqual(response.status, 401)

        token, csrf = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}
        response = await self.client.get("/api/session", headers=headers)
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["username"], "tejian01")
        self.assertEqual(payload["csrf"], csrf)

        response = await self.client.get("/login")
        self.assertEqual(response.status, 200)
        self.assertIn("Vue gateway", await response.text())
        response = await self.client.get("/static-resource/js/app.js")
        self.assertEqual(response.status, 200)
        self.assertIn("gateway", await response.text())

        response = await self.client.post(
            "/api/logout",
            headers={
                "Cookie": f"gmp_session={token}",
                "X-CSRF-Token": csrf,
            },
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get(
            "/api/session",
            headers={"Cookie": f"gmp_session={token}"},
        )
        self.assertEqual(response.status, 401)

    async def test_login_failure_rate_limit(self) -> None:
        for _ in range(5):
            response = await self.client.post(
                "/api/login",
                json={"username": "tejian01", "password": "wrong-password"},
            )
            self.assertEqual(response.status, 401)
        response = await self.client.post(
            "/api/login",
            json={"username": "tejian01", "password": "test-password-123"},
        )
        self.assertEqual(response.status, 429)

    async def test_login_csrf_and_xml_configuration(self) -> None:
        token, csrf = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}
        response = await self.client.put(
            "/api/config",
            headers=headers,
            json={"device_code": "D-NEW", "exam_doct": "新医生", "exam_doct_code": "DOC-NEW"},
        )
        self.assertEqual(response.status, 403)
        headers["X-CSRF-Token"] = csrf
        response = await self.client.put(
            "/api/config",
            headers=headers,
            json={
                "device_code": "D-NEW",
                "exam_doct": "新医生",
                "exam_doct_code": "DOC-NEW",
                "upload_enabled": True,
                "endpoint": "http://127.0.0.1:9999/upload",
                "timeout_seconds": 12,
                "retry_interval_seconds": 15,
                "max_attempts": 4,
                "cleanup_enabled": True,
                "cleanup_interval_hours": 12,
                "report_retention_days": 45,
                "log_retention_days": 21,
            },
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        xml = (Path(self.temp.name) / "data" / "device" / "ReportInfo.xml").read_text(encoding="utf-8")
        self.assertIn("<DeviceCode>D-NEW</DeviceCode>", xml)
        self.assertIn("<ExamDoct>新医生</ExamDoct>", xml)
        self.assertIn("<ExamDoctCode>DOC-NEW</ExamDoctCode>", xml)
        self.assertLess(xml.index("<ExamDoct>"), xml.index("<ExamDoctCode>"))
        self.assertNotIn("xmlns", xml)
        response = await self.client.get("/api/config", headers=headers)
        saved = await response.json()
        self.assertNotIn("username", saved)
        self.assertNotIn("password", saved)
        self.assertEqual(saved["cleanup_interval_hours"], 12)
        self.assertEqual(saved["report_retention_days"], 45)
        self.assertEqual(saved["log_retention_days"], 21)

    async def test_invalid_cleanup_config_does_not_modify_report_info(self) -> None:
        token, csrf = await self._login()
        headers = {
            "Cookie": f"gmp_session={token}",
            "X-CSRF-Token": csrf,
        }
        report_info_path = Path(self.temp.name) / "data" / "device" / "ReportInfo.xml"
        original_xml = report_info_path.read_bytes()

        response = await self.client.put(
            "/api/config",
            headers=headers,
            json={
                "device_code": "D-BAD",
                "exam_doct": "Doctor Bad",
                "exam_doct_code": "DOC-BAD",
                "cleanup_interval_hours": 0,
            },
        )

        self.assertEqual(response.status, 400)
        self.assertEqual(report_info_path.read_bytes(), original_xml)

    async def test_authenticated_dashboard_uses_vue_bundle(self) -> None:
        token, _ = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}

        response = await self.client.get("/", headers=headers)
        self.assertEqual(response.status, 200)
        dashboard = await response.text()
        self.assertIn("Vue gateway", dashboard)

    async def test_reports_api_supports_pagination_and_status_filters(self) -> None:
        token, _ = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}
        root = Path(self.temp.name) / "data" / "reports_pdf"
        root.mkdir(parents=True, exist_ok=True)
        snapshot = self.web.report_info.snapshot()

        uploaded = root / "uploaded.pdf"
        uploaded.write_bytes(b"uploaded")
        uploaded_id = self.uploader.store.enqueue(uploaded, snapshot, "msc")
        self.assertIsNotNone(uploaded_id)
        self.uploader.store.finish(int(uploaded_id), True, 1, 3, 60, 200, "", "ok")

        failed = root / "failed.pdf"
        failed.write_bytes(b"failed")
        failed_id = self.uploader.store.enqueue(failed, snapshot, "printer")
        self.assertIsNotNone(failed_id)
        self.uploader.store.finish(int(failed_id), False, 1, 1, 60, 500, "failed", "")

        pending = root / "pending.pdf"
        pending.write_bytes(b"pending")
        self.assertIsNotNone(self.uploader.store.enqueue(pending, snapshot, "msc"))

        response = await self.client.get(
            "/api/reports?page=1&page_size=1&status=failed",
            headers=headers,
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["jobs"][0]["status"], "exhausted")

        response = await self.client.get("/api/reports?start=20&end=10", headers=headers)
        self.assertEqual(response.status, 400)

    async def test_manual_cleanup_requires_csrf_and_exposes_status(self) -> None:
        token, csrf = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}

        response = await self.client.get("/api/maintenance", headers=headers)
        status = await response.json()
        self.assertEqual(response.status, 200, status)
        self.assertIn("next_run_at", status)

        response = await self.client.post(
            "/api/maintenance/cleanup",
            headers=headers,
            json={"kind": "logs"},
        )
        self.assertEqual(response.status, 403)

        response = await self.client.post(
            "/api/maintenance/cleanup",
            headers={**headers, "X-CSRF-Token": csrf},
            json={"kind": "logs"},
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["kind"], "logs")
        self.assertEqual(payload["result"]["journal_output"], "vacuumed")


if __name__ == "__main__":
    unittest.main()
