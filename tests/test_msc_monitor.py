from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gadget_msc_printer.config import MscConfig
from gadget_msc_printer.msc_monitor import MscMonitor


class StubConverter:
    def __init__(self, succeeds: bool) -> None:
        self.succeeds = succeeds

    def convert(self, source: Path, source_type: str) -> Path | None:
        if not self.succeeds:
            return None
        target = source.with_suffix(".converted.pdf")
        target.write_bytes(source.read_bytes())
        return target


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

    def test_deduplication_can_be_disabled_for_repeated_msc_files(self) -> None:
        self.monitor.mount_dir.mkdir(parents=True)
        self.monitor.output_dir.mkdir(parents=True)
        self.monitor.state_dir.mkdir(parents=True)
        self.monitor.records_file.touch()
        source = self.monitor.mount_dir / "report.pdf"
        source.write_bytes(b"%PDF-1.4\nsame-test-content\n%%EOF\n")

        self.assertEqual(self.monitor._copy_new_files(), 1)
        self.assertEqual(self.monitor._copy_new_files(), 0)

        self.monitor.config.deduplicate = False
        self.assertEqual(self.monitor._copy_new_files(), 1)
        copies = sorted(self.monitor.output_dir.glob("report*.pdf"))
        self.assertEqual(len(copies), 2)
        self.assertEqual(copies[0].read_bytes(), copies[1].read_bytes())

    def test_auto_delete_requires_successful_conversion(self) -> None:
        self.monitor.mount_dir.mkdir(parents=True)
        self.monitor.output_dir.mkdir(parents=True)
        self.monitor.state_dir.mkdir(parents=True)
        self.monitor.records_file.touch()
        source = self.monitor.mount_dir / "report.pdf"
        source.write_bytes(b"%PDF-1.4\nreport\n%%EOF\n")
        self.monitor.config.auto_delete = True
        self.monitor.converter = StubConverter(False)

        self.assertEqual(self.monitor._copy_new_files(), 0)
        self.assertTrue(source.exists())
        self.assertEqual(list(self.monitor.output_dir.glob("report*.pdf")), [])

        source.write_bytes(b"%PDF-1.4\nsecond report\n%%EOF\n")
        self.monitor.converter = StubConverter(True)
        self.assertEqual(self.monitor._copy_new_files(), 1)
        self.assertFalse(source.exists())

    def test_protected_file_is_backed_up_restored_and_not_collected(self) -> None:
        self.monitor.mount_dir.mkdir(parents=True)
        self.monitor.state_dir.mkdir(parents=True)
        self.monitor.config.protected_files = ["DEVICE.INI"]
        self.monitor.config.restore_protected_files = True
        source = self.monitor.mount_dir / "DEVICE.INI"
        source.write_text("marker=1", encoding="utf-8")

        self.monitor._synchronize_protected_files()
        seed = self.monitor.protected_seed_dir / "DEVICE.INI"
        self.assertEqual(seed.read_text(encoding="utf-8"), "marker=1")
        self.assertEqual(self.monitor._iter_files(), [])

        source.unlink()
        self.monitor._synchronize_protected_files()
        self.assertEqual(source.read_text(encoding="utf-8"), "marker=1")


if __name__ == "__main__":
    unittest.main()
