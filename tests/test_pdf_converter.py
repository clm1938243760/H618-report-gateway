from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
