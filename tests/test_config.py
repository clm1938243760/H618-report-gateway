from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gadget_msc_printer.config import (
    GADGET_MODES,
    AppConfig,
    has_hid,
    is_msc_mode,
    load_config,
    resolve_udc_device,
    save_config,
    validate_config,
)


class ConfigTests(unittest.TestCase):
    def test_round_trip_contains_k2b_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            config = AppConfig()
            config.device.device_code = "DEVICE-01"
            config.device.exam_doct = "测试医生"
            config.device.exam_doct_code = "DOCTOR-02"
            config.cleanup.interval_hours = 12
            config.cleanup.report_retention_days = 45
            config.cleanup.log_retention_days = 21
            save_config(path, config)
            loaded = load_config(path)
        self.assertEqual(loaded.gadget.mode, "msc")
        self.assertEqual(loaded.gadget.udc_device, "auto")
        self.assertEqual(loaded.web.port, 443)
        self.assertEqual(loaded.web.compatibility_port, 8443)
        self.assertEqual(loaded.web.username, "tejian01")
        self.assertEqual(loaded.web.password, "julei123#")
        self.assertEqual(loaded.web.static_dir, "/opt/gadget-msc-printer/portal/portal/dist")
        self.assertEqual(loaded.hotspot.device, "wlan1")
        self.assertEqual(loaded.hotspot.ssid, "JVLEI-Gateway")
        self.assertFalse(loaded.hotspot.autostart)
        self.assertEqual(loaded.hotspot.idle_timeout_minutes, 30)
        self.assertEqual(loaded.upload.hospital_code, "tejian01")
        self.assertTrue(loaded.upload.deduplicate)
        self.assertTrue(loaded.msc.deduplicate)
        self.assertFalse(loaded.msc.auto_delete)
        self.assertTrue(loaded.msc.restore_protected_files)
        self.assertEqual(loaded.printer.driver_profile, "universal")
        self.assertEqual(loaded.device.device_code, "DEVICE-01")
        self.assertEqual(loaded.device.exam_doct, "测试医生")
        self.assertEqual(loaded.cleanup.interval_hours, 12)
        self.assertEqual(loaded.cleanup.report_retention_days, 45)
        self.assertEqual(loaded.cleanup.log_retention_days, 21)
        self.assertEqual(loaded.printer.usb_vendor_id, "0x0525")
        self.assertEqual(loaded.printer.usb_product_id, "0xa4a8")
        self.assertEqual(loaded.printer.usb_manufacturer, "JVLEI")
        self.assertIn("MFG:JVLEI", loaded.printer.usb_pnp_string)
        self.assertEqual(loaded.printer.usb_product, "K2B USB Printer")

    def test_legacy_printer_identity_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(
                "printer:\n"
                "  usb_vendor_id: '0xffff'\n"
                "  usb_product_id: '0xeeee'\n"
                "  usb_manufacturer: KICKPI\n"
                "  usb_pnp_string: 'MFG:KICKPI;CMD:RAW;'\n",
                encoding="utf-8",
            )
            loaded = load_config(path)
        self.assertEqual(loaded.printer.usb_vendor_id, "0x0525")
        self.assertEqual(loaded.printer.usb_product_id, "0xa4a8")
        self.assertEqual(loaded.printer.usb_manufacturer, "JVLEI")
        self.assertIn("MFG:JVLEI", loaded.printer.usb_pnp_string)

    def test_auto_udc_resolves_single_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "5100000.usb").mkdir()
            self.assertEqual(resolve_udc_device("auto", directory), "5100000.usb")

    def test_auto_udc_rejects_ambiguous_controllers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "udc-a").mkdir()
            Path(directory, "udc-b").mkdir()
            with self.assertRaisesRegex(RuntimeError, "multiple USB device controllers"):
                resolve_udc_device("auto", directory)

    def test_explicit_udc_does_not_require_sysfs(self) -> None:
        self.assertEqual(resolve_udc_device("custom.udc", "missing"), "custom.udc")

    def test_invalid_mode_is_rejected(self) -> None:
        config = AppConfig()
        config.gadget.mode = "both"
        with self.assertRaisesRegex(ValueError, "msc_hid"):
            validate_config(config)

    def test_all_four_gadget_modes_are_valid(self) -> None:
        for mode in GADGET_MODES:
            with self.subTest(mode=mode):
                config = AppConfig()
                config.gadget.mode = mode
                validate_config(config)
        self.assertTrue(is_msc_mode("msc"))
        self.assertTrue(is_msc_mode("msc_hid"))
        self.assertFalse(is_msc_mode("printer_hid"))
        self.assertTrue(has_hid("msc_hid"))
        self.assertTrue(has_hid("printer_hid"))
        self.assertFalse(has_hid("printer"))

    def test_http_configuration_port_is_rejected(self) -> None:
        config = AppConfig()
        config.web.port = 8080
        with self.assertRaisesRegex(ValueError, "443"):
            validate_config(config)

    def test_invalid_web_credentials_are_rejected(self) -> None:
        config = AppConfig()
        config.web.username = ""
        with self.assertRaisesRegex(ValueError, "username"):
            validate_config(config)
        config.web.username = "tejian01"
        config.web.password = "short"
        with self.assertRaisesRegex(ValueError, "at least 8"):
            validate_config(config)

    def test_invalid_printer_profile_and_protected_path_are_rejected(self) -> None:
        config = AppConfig()
        config.printer.driver_profile = "vendor-magic"
        with self.assertRaisesRegex(ValueError, "driver_profile"):
            validate_config(config)
        config.printer.driver_profile = "universal"
        config.msc.protected_files = ["../outside.ini"]
        with self.assertRaisesRegex(ValueError, "relative paths"):
            validate_config(config)

    def test_invalid_hotspot_configuration_is_rejected(self) -> None:
        config = AppConfig()
        config.hotspot.password = "short"
        with self.assertRaisesRegex(ValueError, "hotspot.password"):
            validate_config(config)
        config.hotspot.password = "valid-password"
        config.hotspot.idle_timeout_minutes = 1441
        with self.assertRaisesRegex(ValueError, "idle_timeout_minutes"):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
