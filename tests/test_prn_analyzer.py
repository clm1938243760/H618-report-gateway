from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from gadget_msc_printer.prn_analyzer import analyze_prn, analyze_recent_prn


class PrnAnalyzerTests(unittest.TestCase):
    def test_detects_supported_print_languages(self) -> None:
        samples = {
            "pclxl": b"\x1b%-12345X@PJL ENTER LANGUAGE=PCLXL\r\n) HP-PCL XL;2;0;",
            "pcl": b"\x1b%-12345X@PJL ENTER LANGUAGE=PCL\r\n\x1bE\x1b*t300R",
            "postscript": b"%!PS-Adobe-3.0\n%%Pages: 1\n",
            "pdf": b"%PDF-1.7\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            for expected, content in samples.items():
                with self.subTest(expected=expected):
                    path = Path(directory) / f"{expected}.prn"
                    path.write_bytes(content)
                    result = analyze_prn(path)
                    self.assertEqual(result["protocol"], expected)
                    self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())
                    self.assertTrue(result["header_hex"])

    def test_extracts_pjl_language_and_commands(self) -> None:
        content = b"\x1b%-12345X@PJL JOB NAME=TEST\r\n@PJL ENTER LANGUAGE=PCLXL\r\n) HP-PCL XL;2;0;"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "details.prn"
            path.write_bytes(content)
            result = analyze_prn(path)
        self.assertEqual(result["declared_language"], "PCLXL")
        self.assertEqual(result["converter"], "GhostPCL")
        self.assertEqual(len(result["pjl_commands"]), 2)
        self.assertIn("@PJL JOB NAME=TEST", result["pjl_commands"])

    def test_unknown_binary_is_not_claimed_as_convertible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.prn"
            path.write_bytes(b"\x00\x81\xfe\x00vendor-private-stream")
            result = analyze_prn(path)
        self.assertEqual(result["protocol"], "unknown")
        self.assertEqual(result["confidence"], "low")

    def test_recent_analysis_is_limited_to_prn_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.prn").write_bytes(b"%PDF-1.4")
            (root / "ignore.txt").write_text("not a print job", encoding="utf-8")
            jobs = analyze_recent_prn(root, 10)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["name"], "one.prn")

    def test_receive_time_includes_utc_timezone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timed.prn"
            path.write_bytes(b"%PDF-1.7")
            timestamp = 1_750_000_000
            os.utime(path, (timestamp, timestamp))
            result = analyze_prn(path)

        self.assertEqual(result["modified_at"], timestamp)
        self.assertEqual(result["modified_time"], "2025-06-15T15:06:40+00:00")


if __name__ == "__main__":
    unittest.main()
