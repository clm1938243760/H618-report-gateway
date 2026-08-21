from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from gadget_msc_printer.prn_analyzer import (
    C_GROUP_CAPABILITIES,
    analyze_prn,
    analyze_recent_prn,
)


class PrnAnalyzerTests(unittest.TestCase):
    def test_c_group_capability_catalog_is_complete_and_ordered(self) -> None:
        self.assertEqual(
            [item["id"] for item in C_GROUP_CAPABILITIES],
            [f"C{number:02d}" for number in range(1, 12)],
        )
        self.assertEqual(len({item["protocols"] for item in C_GROUP_CAPABILITIES}), 11)
        self.assertTrue(all(item["models"] for item in C_GROUP_CAPABILITIES))
        self.assertTrue(all(item["evidence"] for item in C_GROUP_CAPABILITIES))

    def test_detects_modern_driverless_print_formats(self) -> None:
        samples = {
            "pwg_raster": (b"RaS2PwgRaster\x00" + b"\x00" * 64, "pwgtopdf"),
            "cups_raster": (b"3SaR" + b"\x00" * 64, "pwgtopdf"),
            "pclm": (b"%PDF-1.3\n% PCLm 1.0\n%%EOF\n", "直接保留PDF"),
            "apple_urf": (b"UNIRAST\x00" + b"\x00" * 64, "pwgtopdf"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for expected, (content, converter) in samples.items():
                with self.subTest(expected=expected):
                    path = Path(directory) / f"{expected}.prn"
                    path.write_bytes(content)
                    result = analyze_prn(path)
                    self.assertEqual(result["protocol"], expected)
                    self.assertEqual(result["converter"], converter)
                    self.assertEqual(result["confidence"], "high")

    def test_detects_image_payloads_saved_with_prn_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = {
                "jpeg": ("JPEG", {}),
                "png": ("PNG", {}),
                "bmp": ("BMP", {}),
                "tiff": ("TIFF", {}),
                "pcx": ("PCX", {}),
            }
            for expected, (image_format, options) in samples.items():
                path = root / f"{expected}.prn"
                image = Image.new("RGB", (8, 8), "white")
                try:
                    image.save(path, image_format, **options)
                finally:
                    image.close()
                result = analyze_prn(path)
                self.assertEqual(result["protocol"], expected)
                self.assertEqual(result["converter"], "Pillow")

    def test_detects_hpgl_and_xps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hpgl = root / "plot.prn"
            hpgl.write_bytes(b"IN;SP1;PA100,100;PD500,100,500,500;PU;SP0;")
            xps = root / "fixed.prn"
            with zipfile.ZipFile(xps, "w", compression=zipfile.ZIP_DEFLATED) as package:
                package.writestr(
                    "[Content_Types].xml",
                    '<Types><Override ContentType="application/vnd.ms-package.xps-fixedpage+xml" /></Types>',
                )
                package.writestr("FixedDocumentSequence.fdseq", "<FixedDocumentSequence />")
                package.writestr("Documents/1/Pages/1.fpage", "<FixedPage />")

            hpgl_result = analyze_prn(hpgl)
            xps_result = analyze_prn(xps)

        self.assertEqual(hpgl_result["protocol"], "hpgl")
        self.assertEqual(hpgl_result["converter"], "GhostPCL")
        self.assertEqual(xps_result["protocol"], "xps")
        self.assertEqual(xps_result["converter"], "xpstopdf/GhostXPS")

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

    def test_distinguishes_pcl3gui_and_epson_languages(self) -> None:
        samples = {
            "pcl3gui": b"@PJL ENTER LANGUAGE=PCL3GUI\r\nprivate",
            "escp": b"\x1b@\x1bP\x1b3\x18\x1b*\x00\x01\x00\x80\x0c",
            "escp2": b"\x1b@\x1b(G\x01\x00\x01\x1b(U\x01\x00\x0a\x0c",
            "escpr": b"@EJL JOB\r\nESC/P-R raster payload",
            "escpage": b"@PJL ENTER LANGUAGE=ESC/PAGE\r\nprivate",
        }
        results = {}
        with tempfile.TemporaryDirectory() as directory:
            for expected, content in samples.items():
                with self.subTest(expected=expected):
                    path = Path(directory) / f"{expected}.prn"
                    path.write_bytes(content)
                    result = analyze_prn(path)
                    results[expected] = result
                    self.assertEqual(result["protocol"], expected)
        self.assertEqual(results["pcl3gui"]["converter"], "C组：仅识别")
        self.assertIn("保留原始PRN", results["pcl3gui"]["conversion_detail"])
        self.assertEqual(results["escpage"]["declared_language"], "ESC/PAGE")

    def test_reports_escp2_profile_hint_and_profile_used(self) -> None:
        content = (
            b"\x1b@\x1b(R\x08\x00\x00REMOTE1"
            b"PM\x02\x00\x00\x00SN\x03\x00\x00\x00\x01\x1b\x00\x00\x00"
            b"\x1b(G\x01\x00\x01\x1b(U\x01\x00\x0a"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "xp440.prn"
            path.write_bytes(content)
            path.with_suffix(".prn.meta.json").write_text(
                json.dumps({"escp2_profile_used": "xp410"}), encoding="utf-8"
            )
            result = analyze_prn(path)

        self.assertEqual(result["protocol"], "escp2")
        self.assertEqual(result["escp2_profile_hint"], "xp410")
        self.assertEqual(result["escp2_profile_used"], "xp410")
        self.assertIn("PM/SN", result["escp2_profile_evidence"])

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

    def test_detects_zjstream_and_hp_acl_firmware(self) -> None:
        samples = {
            "zjstream": b"\x1b%-12345X@PJL JOB\r\nJZJZpage-data",
            "hp_acl_firmware": b"JZJZ\x00agiACLDownload\x00HP LaserJet 1020",
        }
        with tempfile.TemporaryDirectory() as directory:
            for expected, content in samples.items():
                with self.subTest(expected=expected):
                    path = Path(directory) / f"{expected}.prn"
                    path.write_bytes(content)
                    result = analyze_prn(path)
                    self.assertEqual(result["protocol"], expected)
                    self.assertEqual(result["confidence"], "high")

    def test_detects_offline_private_raster_languages(self) -> None:
        samples = {
            "spl": b"\x1b%-12345X@PJL ENTER LANGUAGE = QPDL\r\nprivate",
            "xqx": b"\x1b%-12345X@PJL JOB\r\n,XQXprivate",
            "hiperc": b"@PJL ENTER LANGUAGE=HIPERC\r\nprivate",
            "hbpl": b"@PJL ENTER LANGUAGE=HBPL\r\nprivate",
            "ddst": (
                b"@PJL SET COMPRESS=JBIG\r\n@PJL SET PAGESTATUS=START\r\n"
                b"@PJL SET IMAGELEN=1234\r\nprivate"
            ),
            "lavaflow": b"@PJL ENTER LANGUAGE=LAVAFLOW\r\nprivate",
            "opl": b"Event=StartOfJob;RasterObject.Compression=JBIG;private",
            "slx": b"\xa5SLX\x00\x00private",
            "oakt": b"PJL preamble\r\nOAKTprivate",
            "gipd": b"offset-table GDIJprivate GDIPpage",
            "brother_hbp": (
                b"\x1b%-12345X@PJL\r\n@PJL SET RAS1200MODE = FALSE\r\n"
                b"@PJL ENTER LANGUAGE = PCL\r\n\x1bE\x1b*b1030m3w\x00\x01\x02"
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            for expected, content in samples.items():
                with self.subTest(expected=expected):
                    path = Path(directory) / f"{expected}.prn"
                    path.write_bytes(content)
                    result = analyze_prn(path)
                    self.assertEqual(result["protocol"], expected)
                    self.assertEqual(result["confidence"], "high")
                    if expected == "gipd":
                        self.assertEqual(result["converter"], "仅采集")
                        self.assertIn("不能导出页面", result["conversion_detail"])
                    else:
                        self.assertNotEqual(result["converter"], "仅采集")

    def test_detects_c_group_protocols_as_identification_only(self) -> None:
        afp_record = lambda payload: (
            b"\x5a"
            + (8 + len(payload)).to_bytes(2, "big")
            + b"\xd3\xa8"
            + b"\x00\x00\x00"
            + payload
        )
        samples = {
            "pantum_gdi": b"Pantum GDI printer stream",
            "sharp_splc": b"SHARP CORPORATION\n@PJL ENTER LANGUAGE=SPLC\nprivate",
            "ricoh_rpcs": b"@PJL ENTER LANGUAGE=RPCS\nprivate",
            "ibm_afp": afp_record(b"one") + afp_record(b"two"),
            "zpl": b"^XA\n^FO20,20^A0N,30,30^FDReport^FS\n^XZ",
            "epl": b"N\r\nA50,50,0,4,1,1,N,Report\r\nP1\r\n",
            "cpcl": b"! 0 200 200 406 1\nPW 384\nT 0 0 30 40 Report\nPRINT\n",
            "printrex": b"PRINTREX raster stream",
        }
        with tempfile.TemporaryDirectory() as directory:
            for expected, content in samples.items():
                with self.subTest(expected=expected):
                    path = Path(directory) / f"{expected}.prn"
                    path.write_bytes(content)
                    result = analyze_prn(path)
                    self.assertEqual(result["protocol"], expected)
                    self.assertEqual(result["confidence"], "high")
                    self.assertEqual(result["converter"], "C组：仅识别")

    def test_splc_without_sharp_context_keeps_samsung_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "splc.prn"
            path.write_bytes(b"@PJL ENTER LANGUAGE=SPLC\r\nprivate")
            result = analyze_prn(path)

        self.assertEqual(result["protocol"], "spl")
        self.assertEqual(result["converter"], "qpdldecode")

    def test_private_raster_analysis_reports_stream_resolution(self) -> None:
        page_header = bytearray(16)
        page_header[0] = 6
        page_header[14:16] = (12).to_bytes(2, "big")
        content = (
            b"@PJL ENTER LANGUAGE = QPDL\r\n" + b"\x00" + bytes(page_header)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qpdl.prn"
            path.write_bytes(content)
            result = analyze_prn(path)

        self.assertEqual(result["protocol"], "spl")
        self.assertEqual(result["raster_dpi_x"], 1200)
        self.assertEqual(result["raster_dpi_y"], 600)

    def test_brother_hbp_is_not_misreported_as_standard_pcl(self) -> None:
        content = (
            b"\x00" * 128
            + b"\x1b%-12345X@PJL\n@PJL SET RAS1200MODE = FALSE\n"
            + b"@PJL SET RESOLUTION = 600\n@PJL ENTER LANGUAGE = PCL\n"
            + b"\x1bE\x1b*b1030m66w\x00\x40"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brother-hbp.prn"
            path.write_bytes(content)
            result = analyze_prn(path)

        self.assertEqual(result["protocol"], "brother_hbp")
        self.assertEqual(result["converter"], "审核版 brdecode")
        self.assertEqual(result["declared_language"], "PCL")

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

    def test_capture_metadata_adds_boundary_and_timing_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "captured.prn"
            path.write_bytes(b"\x1bE\x1b*t300Rpage\x1bE\x1b%-12345X")
            path.with_suffix(".prn.meta.json").write_text(
                json.dumps(
                    {
                        "protocol": "pcl",
                        "completion_reason": "pcl_uel",
                        "first_byte_at": "2026-08-14T00:00:00.000+00:00",
                        "last_byte_at": "2026-08-14T00:00:01.250+00:00",
                        "boundary_detected_at": "2026-08-14T00:00:01.250+00:00",
                        "receive_duration_ms": 1250.0,
                        "completion_duration_ms": 1250.0,
                        "received_bytes": 31,
                        "conversion_started_at": "2026-08-14T00:00:01.251+00:00",
                        "pdf_ready_at": "2026-08-14T00:00:01.501+00:00",
                        "conversion_duration_ms": 250.0,
                        "conversion_status": "completed",
                    }
                ),
                encoding="utf-8",
            )
            result = analyze_prn(path)

        self.assertTrue(result["capture_metadata"])
        self.assertEqual(result["completion_reason_label"], "PCL UEL 结束")
        self.assertEqual(result["receive_duration_ms"], 1250.0)
        self.assertEqual(result["conversion_duration_ms"], 250.0)
        self.assertEqual(result["conversion_status_label"], "转换完成")

    def test_escpr_completion_reason_has_a_chinese_label(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "epson.prn"
            path.write_bytes(b"ESC/P-R")
            path.with_suffix(".prn.meta.json").write_text(
                json.dumps({"completion_reason": "escpr_endj"}),
                encoding="utf-8",
            )
            result = analyze_prn(path)

        self.assertEqual(result["completion_reason_label"], "ESC/P-R EndJob 结束")

    def test_invalid_capture_metadata_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.prn"
            path.write_bytes(b"%PDF-1.7")
            path.with_suffix(".prn.meta.json").write_text("not-json", encoding="utf-8")
            result = analyze_prn(path)

        self.assertFalse(result["capture_metadata"])
        self.assertIsNone(result["receive_duration_ms"])

    def test_historical_c_group_failure_is_displayed_as_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capt.prn"
            path.write_bytes(b"@PJL ENTER LANGUAGE=CAPT\r\nprivate")
            path.with_suffix(".prn.meta.json").write_text(
                json.dumps(
                    {
                        "conversion_status": "failed",
                        "conversion_error": "CAPT is identification-only",
                    }
                ),
                encoding="utf-8",
            )

            result = analyze_prn(path)

        self.assertEqual(result["conversion_status"], "retained")
        self.assertEqual(result["conversion_status_label"], "仅识别，已保留")
        self.assertEqual(result["conversion_error"], "")
        self.assertIn("identification-only", result["conversion_skip_reason"])


if __name__ == "__main__":
    unittest.main()
