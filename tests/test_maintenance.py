from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from subprocess import CompletedProcess

from gadget_msc_printer.config import AppConfig
from gadget_msc_printer.maintenance import MaintenanceManager
from gadget_msc_printer.report_info import ReportInfoManager
from gadget_msc_printer.report_upload import ReportJobStore


class MaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = AppConfig()
        self.config.runtime.data_dir = str(self.root / "data")
        self.config.device.device_code = "DEVICE"
        self.config.device.exam_doct = "Doctor"
        self.config.device.exam_doct_code = "DOC"
        self.config.device.report_info_path = str(self.root / "data" / "device" / "ReportInfo.xml")
        self.config.upload.state_db = str(self.root / "data" / "state" / "jobs.sqlite3")
        self.config.pdf.output_dir = str(self.root / "data" / "reports_pdf")
        self.config.printer.output_dir = str(self.root / "data" / "print_jobs")
        self.config.msc.output_dir = str(self.root / "data" / "msc_files")
        self.store = ReportJobStore(self.config.upload.state_db)
        report_info = ReportInfoManager(self.config.device)
        self.snapshot = report_info.write("DEVICE", "Doctor", "DOC")
        self.commands: list[list[str]] = []

        def command_runner(command, **kwargs):
            self.commands.append(command)
            return CompletedProcess(command, 0, "Vacuuming done", "")

        self.manager = MaintenanceManager(
            self.config.cleanup,
            self.config.runtime,
            self.config.pdf,
            self.config.printer,
            self.config.msc,
            self.store,
            command_runner=command_runner,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _age_job(self, job_id: int, days: int) -> None:
        with closing(self.store._connect()) as connection:
            connection.execute(
                "UPDATE report_jobs SET created_at=?, updated_at=? WHERE id=?",
                (time.time() - days * 86400, time.time() - days * 86400, job_id),
            )
            connection.commit()

    def test_report_cleanup_deletes_only_expired_uploaded_jobs(self) -> None:
        report_root = Path(self.config.pdf.output_dir)
        report_root.mkdir(parents=True)

        uploaded = report_root / "uploaded.pdf"
        uploaded.write_bytes(b"uploaded")
        uploaded_id = self.store.enqueue(uploaded, self.snapshot, "msc")
        self.assertIsNotNone(uploaded_id)
        self.store.finish(int(uploaded_id), True, 1, 3, 60, 200, "", "ok")
        self._age_job(int(uploaded_id), 40)

        failed = report_root / "failed.pdf"
        failed.write_bytes(b"failed")
        failed_id = self.store.enqueue(failed, self.snapshot, "printer")
        self.assertIsNotNone(failed_id)
        self.store.finish(int(failed_id), False, 1, 1, 60, 500, "failed", "")
        self._age_job(int(failed_id), 40)

        old_raw = Path(self.config.printer.output_dir) / "old.prn"
        old_raw.parent.mkdir(parents=True)
        old_raw.write_bytes(b"raw")
        old_time = time.time() - 40 * 86400
        os.utime(old_raw, (old_time, old_time))

        recent_raw = Path(self.config.msc.output_dir) / "recent.pdf"
        recent_raw.parent.mkdir(parents=True)
        recent_raw.write_bytes(b"recent")

        result = self.manager.cleanup_reports(30)

        self.assertEqual(result["jobs_deleted"], 1)
        self.assertFalse(uploaded.exists())
        self.assertTrue(failed.exists())
        self.assertFalse(old_raw.exists())
        self.assertTrue(recent_raw.exists())
        jobs = self.store.list_page(page_size=10)
        self.assertEqual(jobs["total"], 1)
        self.assertEqual(jobs["jobs"][0]["status"], "exhausted")

    def test_log_cleanup_vacuums_journal_and_removes_old_app_logs(self) -> None:
        log = Path(self.config.runtime.data_dir) / "logs" / "gateway.log.1"
        log.parent.mkdir(parents=True)
        log.write_text("old", encoding="utf-8")
        old_time = time.time() - 20 * 86400
        os.utime(log, (old_time, old_time))

        result = self.manager.cleanup_logs(7)

        self.assertEqual(self.commands, [["journalctl", "--vacuum-time=7d"]])
        self.assertEqual(result["files_deleted"], 1)
        self.assertFalse(log.exists())


class MaintenanceWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_runs_automatic_cleanup_when_due(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig()
            config.runtime.data_dir = str(root / "data")
            config.upload.state_db = str(root / "data" / "state" / "jobs.sqlite3")
            config.pdf.output_dir = str(root / "data" / "reports_pdf")
            config.printer.output_dir = str(root / "data" / "print_jobs")
            config.msc.output_dir = str(root / "data" / "msc_files")
            commands: list[list[str]] = []

            def command_runner(command, **kwargs):
                commands.append(command)
                return CompletedProcess(command, 0, "vacuumed", "")

            manager = MaintenanceManager(
                config.cleanup,
                config.runtime,
                config.pdf,
                config.printer,
                config.msc,
                ReportJobStore(config.upload.state_db),
                command_runner=command_runner,
            )
            manager._next_run_at = 0
            task = asyncio.create_task(manager.run())
            for _ in range(30):
                if commands:
                    break
                await asyncio.sleep(0.01)
            manager.stop()
            await asyncio.wait_for(task, timeout=1)

        self.assertEqual(commands, [["journalctl", "--vacuum-time=14d"]])
        self.assertGreater(manager.status()["last_run_at"], 0)


if __name__ == "__main__":
    unittest.main()
