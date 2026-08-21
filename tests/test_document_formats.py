from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from gadget_msc_printer.document_formats import (
    declared_pjl_language,
    detect_c_printer_protocol,
    detect_escp2_profile_hint,
    detect_epson_protocol,
    detect_image_format,
    detect_modern_print_format,
    detect_xps_package,
    looks_like_hpgl,
    looks_like_pcl3gui,
)


def write_xps(path: Path, *, openxps: bool = False) -> None:
    vendor = "openxps" if openxps else "ms-package.xps"
    content_types = f"""<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/FixedDocumentSequence.fdseq"
    ContentType="application/vnd.{vendor}-fixeddocumentsequence+xml" />
  <Override PartName="/Documents/1/Pages/1.fpage"
    ContentType="application/vnd.{vendor}-fixedpage+xml" />
</Types>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("FixedDocumentSequence.fdseq", "<FixedDocumentSequence />")
        package.writestr("Documents/1/Pages/1.fpage", "<FixedPage />")


class DocumentFormatTests(unittest.TestCase):
    def test_recognizes_c_group_protocol_signatures(self) -> None:
        afp_record = lambda payload: (
            b"\x5a"
            + (8 + len(payload)).to_bytes(2, "big")
            + b"\xd3\xa8"
            + b"\x00\x00\x00"
            + payload
        )
        samples = {
            "ufr": b"@PJL ENTER LANGUAGE=UFRII\r\nprivate",
            "capt": b"@PJL ENTER LANGUAGE=CAPT\r\nprivate",
            "pantum_gdi": b"Pantum GDI printer stream",
            "sharp_splc": b"SHARP CORPORATION\r\n@PJL ENTER LANGUAGE=SPLC\r\nprivate",
            "ricoh_rpcs": b"@PJL ENTER LANGUAGE=RPCS\r\nprivate",
            "ibm_afp": afp_record(b"one") + afp_record(b"two"),
            "zpl": b"^XA\n^FO20,20^A0N,30,30^FDReport^FS\n^XZ",
            "epl": b"N\r\nA50,50,0,4,1,1,N,Report\r\nP1\r\n",
            "cpcl": b"! 0 200 200 406 1\nPW 384\nT 0 0 30 40 Report\nPRINT\n",
            "printrex": b"PRINTREX raster stream",
        }
        for expected, content in samples.items():
            with self.subTest(expected=expected):
                self.assertEqual(detect_c_printer_protocol(content), expected)

    def test_c_group_detector_is_conservative_for_ambiguous_streams(self) -> None:
        self.assertIsNone(detect_c_printer_protocol(b"SPLC private data"))
        self.assertIsNone(detect_c_printer_protocol(b"^FO ordinary text ^FD note"))
        self.assertIsNone(detect_c_printer_protocol(b"N\nthis is a note\nP"))
        self.assertIsNone(detect_c_printer_protocol(b"0x5a 00 10 d3 not AFP"))
        self.assertIsNone(
            detect_c_printer_protocol(
                b"%PDF-1.7\n(Pantum GDI UFRII CAPT PRINTREX)\n%%EOF"
            )
        )
        self.assertIsNone(
            detect_c_printer_protocol(
                b"@PJL ENTER LANGUAGE=PCL\r\nSHARP SPLC Pantum GDI report text"
            )
        )

    def test_recognizes_modern_driverless_print_formats(self) -> None:
        samples = {
            "pwg_raster": b"RaS2PwgRaster\x00" + b"\x00" * 128,
            "cups_raster": b"3SaR" + b"\x00" * 128,
            "apple_urf": b"UNIRAST\x00" + b"\x00" * 128,
            "pclm": b"%PDF-1.3\n% PCLm 1.0\n1 0 obj\n",
        }
        for expected, content in samples.items():
            with self.subTest(expected=expected):
                self.assertEqual(detect_modern_print_format(content), expected)

        self.assertIsNone(detect_modern_print_format(b"%PDF-1.7\nordinary PDF\n"))
        self.assertEqual(
            detect_modern_print_format(b"RaS2not-a-PWG-stream"), "cups_raster"
        )

    def test_recognizes_all_cups_raster_sync_byte_orders(self) -> None:
        for sync in (b"RaSt", b"tSaR", b"RaS2", b"2SaR", b"RaS3", b"3SaR"):
            with self.subTest(sync=sync):
                self.assertEqual(
                    detect_modern_print_format(sync + b"\x00" * 128),
                    "cups_raster",
                )

    def test_recognizes_common_image_payload_headers(self) -> None:
        samples = {
            "jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 124,
            "png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 120,
            "bmp": b"BM" + b"\x00" * 126,
            "tiff": b"II*\x00" + b"\x00" * 124,
            "dcx": b"\xb1\x68\xde\x3a" + b"\x00" * 124,
            "pcx": b"\x0a\x05\x01\x08" + b"\x00" * 124,
        }
        for expected, content in samples.items():
            with self.subTest(expected=expected):
                self.assertEqual(detect_image_format(content), expected)
        self.assertIsNone(detect_image_format(b"BM too short"))
        self.assertIsNone(detect_image_format(b"\x0a\xff\x01\x08" + b"\x00" * 124))

    def test_pjl_language_and_pcl3gui_are_matched_exactly(self) -> None:
        pcl = b"\x1b%-12345X@PJL ENTER LANGUAGE=PCL\r\n\x1bE"
        pcl3gui = b"\x1b%-12345X@PJL ENTER LANGUAGE=PCL3GUI\r\nprivate"

        self.assertEqual(declared_pjl_language(pcl), "PCL")
        self.assertFalse(looks_like_pcl3gui(pcl))
        self.assertEqual(declared_pjl_language(pcl3gui), "PCL3GUI")
        self.assertTrue(looks_like_pcl3gui(pcl3gui))

    def test_distinguishes_epson_protocol_families(self) -> None:
        samples = {
            "escp": b"\x1b@\x1bP\x1b3\x18\x1b*\x00\x01\x00\x80\x0c",
            "escp2": b"\x1b@\x1b(G\x01\x00\x01\x1b(U\x01\x00\x0a\x0c",
            "escpr": b"@EJL JOB\r\nESC/P-R raster payload",
            "escpage": b"@PJL ENTER LANGUAGE=ESC/PAGE\r\nprivate",
            "epson": b"@EJL 1284.4\r\nunknown payload",
        }
        for expected, content in samples.items():
            with self.subTest(expected=expected):
                self.assertEqual(detect_epson_protocol(content), expected)
        self.assertIsNone(detect_epson_protocol(b"\x1bE\x1b*t300Rplain PCL"))

    def test_detects_binary_escpr_but_not_ejl_alone(self) -> None:
        binary = (
            b"@EJL 1284.4\nESCPRLib"
            b"\x1b(R\x06\x00\x00ESCPR"
            b"\x1bq\x09\x00\x00\x00setq"
            b"\x1bp\x00\x00\x00\x00sttp"
        )
        self.assertEqual(detect_epson_protocol(binary), "escpr")
        self.assertEqual(detect_epson_protocol(b"@EJL 1284.4\nunknown payload"), "epson")

    def test_escp2_profile_hints_require_exact_validated_fingerprints(self) -> None:
        prefix = b"\x1b@\x1b(R\x08\x00\x00REMOTE1"
        suffix = b"\x1b\x00\x00\x00\x1b(G\x01\x00\x01\x1b(U\x01\x00\x0a"
        samples = {
            "xp410": prefix + b"PM\x02\x00\x00\x00SN\x03\x00\x00\x00\x01" + suffix,
            "sr800": (
                prefix
                + b"IR\x02\x00\x00\x01EX\x06\x00\x00\x00\x00\x00\x05\x00"
                + b"PP\x03\x00\x00\x01\xff"
                + suffix
            ),
        }
        for expected, content in samples.items():
            with self.subTest(expected=expected):
                profile, evidence = detect_escp2_profile_hint(content)
                self.assertEqual(profile, expected)
                self.assertIn("Gutenprint", evidence)
                if expected == "xp410":
                    for model in ("XP-440", "L120", "L310", "ET-2750"):
                        self.assertIn(model, evidence)

        unknown, evidence = detect_escp2_profile_hint(
            b"\x1b@\x1b(G\x01\x00\x01\x1b(U\x01\x00\x0a"
        )
        self.assertIsNone(unknown)
        self.assertIn("手动选择", evidence)

    def test_recognizes_pure_and_pcl_wrapped_hpgl(self) -> None:
        pure = b"IN;SP1;PA100,100;PD500,100,500,500;PU;SP0;"
        wrapped = b"\x1bE\x1b%0B" + pure + b"\x1b%0A"

        self.assertTrue(looks_like_hpgl(pure))
        self.assertTrue(looks_like_hpgl(wrapped))

    def test_plain_semicolon_text_is_not_hpgl(self) -> None:
        self.assertFalse(looks_like_hpgl(b"IN; this is an ordinary note; please review;"))

    def test_recognizes_xps_and_openxps_but_not_an_arbitrary_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            xps = root / "report.xps"
            oxps = root / "report.oxps"
            other = root / "other.zip"
            write_xps(xps)
            write_xps(oxps, openxps=True)
            with zipfile.ZipFile(other, "w") as package:
                package.writestr("[Content_Types].xml", "<Types />")
                package.writestr("word/document.xml", "<document />")

            self.assertEqual(detect_xps_package(xps), "xps")
            self.assertEqual(detect_xps_package(oxps), "oxps")
            self.assertIsNone(detect_xps_package(other))


if __name__ == "__main__":
    unittest.main()
