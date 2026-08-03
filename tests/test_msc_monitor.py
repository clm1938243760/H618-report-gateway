from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gadget_msc_printer.config import MscConfig
from gadget_msc_printer.msc_monitor import MscMonitor


class MscMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        gadget = root / "gadget"
        function = gadget / "functions" / "mass_storage.0" / "lun.0"
        function.mkdir(parents=True)
        self.udc_attr = gadget / "UDC"
        self.file_attr = function / "file"
        self.image = root / "ums_shared.img"
        self.image.write_bytes(b"image")
        self.udc_attr.write_text("fcc00000.usb\n", encoding="utf-8")
        self.file_attr.write_text(f"{self.image}\n", encoding="utf-8")
        config = MscConfig(
            gadget_dir=str(gadget),
            udc_device="fcc00000.usb",
            image_path=str(self.image),
            mount_dir=str(root / "mount"),
            output_dir=str(root / "output"),
            state_dir=str(root / "state"),
        )
        self.monitor = MscMonitor(config)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @patch("gadget_msc_printer.msc_monitor.time.sleep")
    def test_configfs_detach_uses_newline_not_zero_byte(self, _sleep) -> None:
        udc = self.monitor._unbind_gadget()
        self.monitor._detach_backing_file()

        self.assertEqual(udc, "fcc00000.usb")
        for content in (self.udc_attr.read_bytes(), self.file_attr.read_bytes()):
            self.assertGreater(len(content), 0)
            self.assertEqual(content.strip(), b"")

    def test_attach_and_bind_restore_values(self) -> None:
        self.udc_attr.write_text("\n", encoding="utf-8")
        self.file_attr.write_text("\n", encoding="utf-8")

        self.monitor._attach_backing_file()
        self.monitor._bind_gadget("fcc00000.usb")

        self.assertEqual(self.file_attr.read_text(encoding="utf-8").strip(), str(self.image))
        self.assertEqual(self.udc_attr.read_text(encoding="utf-8").strip(), "fcc00000.usb")


if __name__ == "__main__":
    unittest.main()
