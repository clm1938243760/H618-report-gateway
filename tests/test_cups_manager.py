from __future__ import annotations

import subprocess
import unittest

from gadget_msc_printer.config import PhysicalPrinterConfig
from gadget_msc_printer.cups_manager import CupsManager


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        key = tuple(command)
        if key == ("lpstat", "-r"):
            return subprocess.CompletedProcess(command, 0, "scheduler is running\n", "")
        if key in {("lpstat", "-d"), ("lpstat", "-p"), ("lpstat", "-v")}:
            return subprocess.CompletedProcess(command, 1, "", "no destinations added")
        if key == ("lpinfo", "-v"):
            return subprocess.CompletedProcess(
                command,
                0,
                "direct usb://HP/HP%20LaserJet%20Pro%20400%20M401dn?serial=HPTEST\n"
                "direct usb://Brother/HL-1218W?serial=ABC\n"
                "network ipp://printer.local/ipp/print\n",
                "",
            )
        if key == ("lpinfo", "-m"):
            return subprocess.CompletedProcess(
                command,
                0,
                "drv:///brlaser.drv/br1200.ppd Brother HL-1200 series, using brlaser\n"
                "drv:///sample.drv/generic.ppd Generic PostScript Printer\n"
                "foomatic-db-compressed-ppds:0/ppd/foomatic-ppd/Generic-PCL_6_PCL_XL_Printer-pxlmono.ppd Generic PCL 6/PCL XL Printer Foomatic/pxlmono\n",
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")


class CupsManagerTests(unittest.TestCase):
    def test_status_treats_empty_queue_as_healthy_and_recommends_brlaser(self) -> None:
        runner = FakeRunner()
        manager = CupsManager(runner)
        status = manager.status(PhysicalPrinterConfig())
        self.assertTrue(status["available"])
        self.assertTrue(status["running"])
        self.assertEqual(status["queues"], [])
        self.assertEqual(status["default_queue"], "")
        self.assertEqual(status["devices"][0]["recommended_profile"], "hp_laserjet_m401_pcl6")
        self.assertEqual(status["devices"][1]["recommended_profile"], "brother_hl1200")
        hp_profile = next(item for item in status["profiles"] if item["value"] == "hp_laserjet_m401_pcl6")
        self.assertTrue(hp_profile["available"])
        self.assertIn("Generic-PCL_6_PCL_XL_Printer-pxlmono.ppd", hp_profile["model"])
        profile = next(item for item in status["profiles"] if item["value"] == "brother_hl1200")
        self.assertTrue(profile["available"])
        self.assertEqual(profile["model"], "drv:///brlaser.drv/br1200.ppd")

    def test_configure_uses_selected_whitelisted_model(self) -> None:
        runner = FakeRunner()
        manager = CupsManager(runner)
        config = PhysicalPrinterConfig(
            enabled=True,
            queue_name="Brother_HL1218W",
            device_uri="usb://Brother/HL-1218W?serial=ABC",
            driver_profile="brother_hl1200",
        )
        result = manager.configure(config)
        self.assertEqual(result["queue_name"], "Brother_HL1218W")
        lpadmin = next(command for command in runner.commands if command[:2] == ["lpadmin", "-p"])
        self.assertIn("drv:///brlaser.drv/br1200.ppd", lpadmin)
        self.assertIn("usb://Brother/HL-1218W?serial=ABC", lpadmin)


if __name__ == "__main__":
    unittest.main()
