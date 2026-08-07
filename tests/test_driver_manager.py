from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from subprocess import CompletedProcess

from gadget_msc_printer.config import AppConfig, validate_config
from gadget_msc_printer.cups_manager import CupsManager
from gadget_msc_printer.driver_manager import DriverManager


PPD = b"""*PPD-Adobe: \"4.3\"\n*Manufacturer: \"JVLEI\"\n*ModelName: \"Test Laser\"\n*NickName: \"Test Laser Driver\"\n*cupsFilter2: \"application/pdf application/vnd.cups-pdf 0 test-filter\"\n"""


class DriverManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = DriverManager(root=self.root / "drivers")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_ppd_upload_is_staged_and_can_be_exposed_as_custom_profile(self) -> None:
        source = self.root / "test.ppd"
        source.write_bytes(PPD)
        staged = self.manager.stage_upload("test.ppd", source)
        self.assertTrue(staged["analysis"]["supported"])
        installed = self.root / "drivers" / "installed" / "test" / "test.ppd"
        installed.parent.mkdir(parents=True)
        installed.write_bytes(PPD)
        self.manager._write_registry(  # noqa: SLF001 - exercising the on-disk reviewed record contract.
            {
                "schema": 1,
                "drivers": [
                    {
                        "id": "test",
                        "label": "Test Laser Driver",
                        "model": str(installed),
                        "source_type": "ppd",
                    }
                ],
            }
        )
        profiles = self.manager.profiles()
        self.assertEqual(profiles[0]["value"], "custom:test")
        cups = CupsManager(
            command_runner=lambda command, timeout: CompletedProcess(command, 0, "", ""),
            custom_profile_provider=self.manager.profiles,
        )
        self.assertTrue(any(item["value"] == "custom:test" for item in cups.driver_profiles()))
        config = AppConfig()
        config.physical_printer.driver_profile = "custom:test"
        validate_config(config)

    def test_unsafe_archive_is_not_accepted(self) -> None:
        source = self.root / "unsafe.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("../escape.ppd", PPD)
        analysis = self.manager.analyze(source)
        self.assertFalse(analysis["supported"])
        self.assertIn("不安全路径", "；".join(analysis["reasons"]))

    def _stage_deb(self, package: str = "vendor-printer") -> str:
        upload_id = "a" * 32
        source_dir = self.manager.staging_dir / upload_id / "source"
        source_dir.mkdir(parents=True)
        source = source_dir / "vendor-printer.deb"
        source.write_bytes(b"not-a-real-deb")
        metadata = {
            "id": upload_id,
            "filename": source.name,
            "path": str(source),
            "analysis": {
                "supported": True,
                "source_type": "deb",
                "sha256": "a" * 64,
                "package": package,
                "version": "1.0",
                "depends": "",
                "warnings": [],
                "maintainer_scripts": [],
            },
        }
        self.manager._stage_meta_path(upload_id).write_text(  # noqa: SLF001 - staged metadata is the install boundary.
            json.dumps(metadata), encoding="utf-8"
        )
        return upload_id

    def test_deb_install_copies_system_ppd_and_registers_profile(self) -> None:
        system_ppd = self.root / "system" / "vendor-printer.ppd"
        system_ppd.parent.mkdir()
        system_ppd.write_bytes(PPD)
        upload_id = self._stage_deb()

        def runner(command: list[str], timeout: int) -> CompletedProcess[str]:
            if command[:3] == ["dpkg-query", "-L", "vendor-printer"]:
                return CompletedProcess(command, 0, f"{system_ppd}\n", "")
            return CompletedProcess(command, 0, "", "")

        self.manager.command_runner = runner
        result = self.manager.install(upload_id)

        model = Path(result["driver"]["model"])
        self.assertTrue(model.is_file())
        self.assertEqual(model.read_bytes(), PPD)
        self.assertEqual(result["driver"]["label"], "Test Laser Driver")
        self.assertTrue(result["profiles"][0]["available"])

    def test_deb_without_ppd_is_marked_unavailable(self) -> None:
        upload_id = self._stage_deb()
        self.manager.command_runner = lambda command, timeout: CompletedProcess(command, 0, "", "")

        result = self.manager.install(upload_id)

        self.assertEqual(result["driver"]["model"], "")
        self.assertFalse(self.manager.drivers()[0]["available"])
        warnings = result["driver"]["analysis"]["warnings"]
        self.assertTrue(any("PPD" in item for item in warnings))
