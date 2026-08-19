from __future__ import annotations

import io
import json
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from subprocess import CompletedProcess

from gadget_msc_printer.driver_catalog import DriverCatalogError, DriverCatalogManager
from jvlei_update.package import build_package


class FakeAptRunner:
    def __init__(self) -> None:
        self.installed: set[str] = set()
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], timeout: int) -> CompletedProcess[str]:
        self.commands.append(command)
        if command[:2] == ["dpkg-query", "-W"]:
            package = command[-1]
            if package in self.installed:
                return CompletedProcess(command, 0, "installed\t1.0", "")
            return CompletedProcess(command, 1, "", "not installed")
        if command[:2] == ["apt-cache", "policy"]:
            return CompletedProcess(
                command,
                0,
                f"{command[-1]}:\n  Installed: (none)\n  Candidate: 1.2.3\n",
                "",
            )
        if command[:2] == ["apt-get", "update"]:
            return CompletedProcess(command, 0, "updated", "")
        if command and command[0] == "apt-get" and "--print-uris" in command:
            package = command[-1]
            return CompletedProcess(
                command,
                0,
                "The following NEW packages will be installed:\n"
                f"  libcupsimage2t64 {package}\n"
                "0 upgraded, 2 newly installed, 0 to remove.\n"
                "Need to get 311 kB of archives.\n"
                "After this operation, 746 kB of additional disk space will be used.\n"
                f"'https://packages.example/{package}.deb' {package}.deb 304462 MD5Sum:abc\n",
                "",
            )
        if command and command[0] == "apt-get" and "install" in command:
            self.installed.add(command[-1])
            return CompletedProcess(command, 0, "installed successfully", "")
        if command[:2] == ["systemctl", "restart"]:
            return CompletedProcess(command, 0, "", "")
        return CompletedProcess(command, 0, "", "")


MODELS = [
    {
        "model": "drv:///brlaser.drv/br1200.ppd",
        "label": "Brother HL-1200 series, using brlaser",
    },
    {
        "model": "foomatic-db-compressed-ppds:0/ppd/foomatic-ppd/Generic-PCL_6_PCL_XL_Printer-pxlmono.ppd",
        "label": "Generic PCL 6/PCL XL Printer Foomatic/pxlmono",
    },
    {
        "model": "drv:///sample.drv/generic.ppd",
        "label": "Generic PostScript Printer",
    },
]


class DriverCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runner = FakeAptRunner()
        self.manager = DriverCatalogManager(
            root=self.root / "catalog",
            model_provider=lambda: list(MODELS),
            command_runner=self.runner,
            public_key=self.root / "public.pem",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_refresh_builds_searchable_stable_catalog(self) -> None:
        first = self.manager.refresh(False)
        self.assertGreaterEqual(first["total"], 3)
        result = self.manager.search(query="Brother HL 1200", page_size=10)
        self.assertGreaterEqual(result["total"], 1)
        model = next(item for item in result["items"] if item["source"] == "cups")
        self.assertEqual(model["package_name"], "printer-driver-brlaser")
        self.assertFalse(model["installed"])
        model_id = model["model_id"]

        self.manager.refresh(False)
        refreshed_ids = {item["model_id"] for item in self.manager.search(query="Brother HL 1200")["items"]}
        self.assertIn(model_id, refreshed_ids)

    def test_bundled_catalog_exposes_models_before_package_installation(self) -> None:
        bundled = self.root / "driver-catalog.json"
        bundled.write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "model_id": "epson-l3250",
                            "manufacturer": "Epson",
                            "model": "Epson L3250 Series",
                            "aliases": ["L3250"],
                            "cups_model": "drv:///escpr.drv/epson-l3250.ppd",
                            "package_name": "printer-driver-escpr",
                            "protocols": ["ESC/P-R"],
                            "verification": "repository",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        manager = DriverCatalogManager(
            root=self.root / "bundled-catalog",
            model_provider=lambda: [],
            command_runner=self.runner,
            public_key=self.root / "public.pem",
            bundled_catalog=bundled,
        )
        manager.refresh(False)
        model = manager.search(query="Epson L3250")["items"][0]
        self.assertEqual(model["model_id"], "epson-l3250")
        self.assertEqual(model["source"], "bundled")
        self.assertFalse(model["installed"])
        self.assertTrue(model["available"])

    def test_device_recommendation_and_ipp_priority(self) -> None:
        self.manager.refresh(False)
        values = self.manager.recommendations(
            [
                {"uri": "usb://Brother/HL-1200", "label": "Brother HL-1200"},
                {"uri": "ipp://printer.local/ipp/print", "label": "Office Printer"},
            ]
        )
        self.assertEqual(values["usb://Brother/HL-1200"][0]["package_name"], "printer-driver-brlaser")
        self.assertEqual(values["ipp://printer.local/ipp/print"][0]["model_id"], "generic-ipp-everywhere")

    def test_known_field_models_have_exact_controlled_aliases(self) -> None:
        self.manager.refresh(False)
        brother = self.manager.search(query="Brother HL-1218W")["items"]
        hp = self.manager.search(query="HP LaserJet Pro 400 M401")["items"]
        self.assertEqual(brother[0]["model_id"], "alias-brother-hl1218w")
        self.assertEqual(brother[0]["package_name"], "printer-driver-brlaser")
        self.assertEqual(hp[0]["model_id"], "alias-hp-laserjet-pro-400-m401")
        self.assertEqual(hp[0]["package_name"], "printer-driver-pxljr")

    def test_plan_and_async_install_use_only_whitelisted_package(self) -> None:
        self.manager.refresh(False)
        model = self.manager.search(query="Brother HL 1200")["items"][0]
        plan = self.manager.plan(model["model_id"])
        self.assertTrue(plan["required"])
        self.assertEqual(plan["package_name"], "printer-driver-brlaser")
        self.assertEqual(plan["download_bytes"], 304462)
        self.assertGreater(plan["install_bytes"], 700000)

        job = self.manager.install_async(model["model_id"])
        deadline = time.time() + 3
        while job["state"] not in {"completed", "failed"} and time.time() < deadline:
            time.sleep(0.02)
            job = self.manager.job(job["job_id"])
        self.assertEqual(job["state"], "completed", job)
        install = next(command for command in self.runner.commands if command and command[0] == "apt-get" and "install" in command and "--print-uris" not in command)
        self.assertEqual(install[-1], "printer-driver-brlaser")
        self.assertIn("--no-install-recommends", install)

    def test_invalid_model_id_cannot_be_used_as_package_name(self) -> None:
        with self.assertRaises(DriverCatalogError):
            self.manager.plan("printer-driver-brlaser;reboot")

    def test_manual_validation_is_separate_from_cups_completion(self) -> None:
        self.manager.refresh(False)
        model = self.manager.search(query="Brother HL 1200")["items"][0]
        self.manager.validate(model["model_id"], "passed", "实机测试页正常")
        verified = self.manager.search(status="verified")["items"]
        self.assertEqual(verified[0]["model_id"], model["model_id"])
        self.assertEqual(verified[0]["validation"]["notes"], "实机测试页正常")

    def test_unsigned_offline_pack_is_rejected(self) -> None:
        payload = self.root / "payload.tar.gz"
        with tarfile.open(payload, "w:gz") as archive:
            data = b"{}"
            info = tarfile.TarInfo("catalog.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        package = self.root / "drivers.jvdrv"
        build_package(
            payload,
            {
                "package_id": "driver-pack-test",
                "package_type": "printer_driver",
                "product": "jvlei-printer-drivers-noble-arm64",
                "version": "1.0.0",
                "arch": "arm64",
                "compatible_versions": ["*"],
                "created_at": "2026-08-18T00:00:00Z",
                "release_notes": "test",
                "git_commit": "test",
                "migration_level": 0,
                "requires_gadget_restart": False,
                "requires_cups_restart": True,
            },
            package,
            allow_unsigned=True,
        )
        with self.assertRaisesRegex(DriverCatalogError, "校验失败"):
            self.manager.stage_offline(package.name, package)


if __name__ == "__main__":
    unittest.main()
