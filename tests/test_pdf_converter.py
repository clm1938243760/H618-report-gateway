from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from gadget_msc_printer.config import PdfConfig
from gadget_msc_printer.pdf_converter import PdfConverter


class PdfConverterTests(unittest.TestCase):
    def test_pdf_copy_does_not_preserve_future_fat_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.pdf"
            source.write_bytes(b"%PDF-1.4\n%%EOF\n")
            future = time.time() + 8 * 60 * 60
            os.utime(source, (future, future))
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            result = converter.convert(source, "msc")

            self.assertIsNotNone(result)
            self.assertLess(result.stat().st_mtime, future - 60)

    def test_unsupported_binary_does_not_create_fake_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "unknown.dat"
            source.write_bytes(b"\x00\x01\x02\x03" * 100)
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf"), ghostpcl=[]))
            result = converter.convert(source, "msc")
            outputs = list((root / "pdf").glob("*.pdf"))
        self.assertIsNone(result)
        self.assertEqual(outputs, [])

    def test_zjstream_is_decoded_to_a_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "zjstream.prn"
            source.write_bytes(
                b"\x1b%-12345X@PJL JOB\r\n"
                b"JZJZsynthetic-stream"
                b"\x1b%-12345X@PJL EOJ\r\n\x1b%-12345X"
            )
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            def decode(command, **kwargs):
                del kwargs
                Path(f"{command[2]}-01-1.pbm").write_bytes(b"P4\n8 1\n\x00")
                return subprocess.CompletedProcess(command, 0, "decoded", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/bin/zjsdecode",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=decode,
                ),
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.read_bytes().startswith(b"%PDF-"))

    def test_hp_acl_firmware_is_ignored_without_running_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "firmware.prn"
            source.write_bytes(b"JZJZ\x00agiACLDownload\x00HP LaserJet 1020")
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            with patch("gadget_msc_printer.pdf_converter.subprocess.run") as run:
                result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertIn("firmware", converter.ignore_reason(source).lower())
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
