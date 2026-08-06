from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gadget_msc_printer.config import PdfConfig, PhysicalPrinterConfig
from gadget_msc_printer.physical_print import PhysicalPrintWorker


class FakeCups:
    def __init__(self) -> None:
        self.printed: list[Path] = []

    def print_file(self, path: Path, config: PhysicalPrinterConfig) -> str:
        self.printed.append(Path(path))
        return f"{config.queue_name}-{len(self.printed)}"


class PhysicalPrintTests(unittest.TestCase):
    def test_existing_pdf_is_baseline_and_only_new_pdf_is_printed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            reports.mkdir()
            old_pdf = reports / "old.pdf"
            old_pdf.write_bytes(b"%PDF-old")
            config = PhysicalPrinterConfig(
                enabled=True,
                auto_print=True,
                queue_name="Physical_Printer",
                device_uri="usb://Brother/HL-1218W",
                state_db=str(root / "physical.sqlite3"),
                file_stable_seconds=0,
            )
            cups = FakeCups()
            worker = PhysicalPrintWorker(config, PdfConfig(output_dir=str(reports)), cups)

            self.assertEqual(worker.initialize_baseline(), 1)
            worker.scan_once()
            self.assertEqual(worker.process_ready(), 0)
            self.assertEqual(cups.printed, [])

            new_pdf = reports / "new.pdf"
            new_pdf.write_bytes(b"%PDF-new")
            self.assertEqual(worker.scan_once(), 1)
            self.assertEqual(worker.process_ready(), 1)
            self.assertEqual(cups.printed, [new_pdf])
            self.assertEqual(worker.status()["counts"]["submitted"], 1)

            with patch(
                "gadget_msc_printer.physical_print._sha256_file",
                side_effect=AssertionError("known PDFs must not be hashed again"),
            ):
                self.assertEqual(worker.scan_once(), 0)


if __name__ == "__main__":
    unittest.main()
