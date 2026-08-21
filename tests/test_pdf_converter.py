from __future__ import annotations

import os
import re
import struct
import subprocess
import tempfile
import time
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from gadget_msc_printer.config import PdfConfig
from gadget_msc_printer.pdf_converter import PWG_TO_PDF, PdfConverter
from gadget_msc_printer.private_raster import private_raster_spec


def write_xps(path: Path) -> None:
    content_types = """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Override PartName="/FixedDocumentSequence.fdseq"
 ContentType="application/vnd.ms-package.xps-fixeddocumentsequence+xml" />
<Override PartName="/Documents/1/Pages/1.fpage"
 ContentType="application/vnd.ms-package.xps-fixedpage+xml" />
</Types>"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("FixedDocumentSequence.fdseq", "<FixedDocumentSequence />")
        package.writestr("Documents/1/Pages/1.fpage", "<FixedPage />")


def write_dcx(path: Path, pages: list[Image.Image]) -> None:
    encoded: list[bytes] = []
    for page in pages:
        buffer = BytesIO()
        page.save(buffer, "PCX")
        encoded.append(buffer.getvalue())
    header = bytearray(4100)
    struct.pack_into("<I", header, 0, 0x3ADE68B1)
    offset = len(header)
    for index, content in enumerate(encoded):
        struct.pack_into("<I", header, 4 + index * 4, offset)
        offset += len(content)
    path.write_bytes(header + b"".join(encoded))


class PdfConverterTests(unittest.TestCase):
    def test_qpdl_pdf_uses_asymmetric_stream_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "qpdl.prn"
            page_header = bytearray(16)
            page_header[0] = 6
            page_header[14:16] = (12).to_bytes(2, "big")
            source.write_bytes(
                b"@PJL ENTER LANGUAGE = QPDL\r\n" + b"\x00" + bytes(page_header)
            )
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            def decode(command, **kwargs):
                del kwargs
                Image.new("1", (1200, 600), 1).save(f"{command[2]}-01-4.pbm")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/bin/qpdldecode",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=decode,
                ),
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result, converter.last_error)
            assert result is not None
            media_box = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)", result.read_bytes())
            self.assertIsNotNone(media_box)
            assert media_box is not None
            self.assertAlmostEqual(float(media_box.group(1)), 72.0)
            self.assertAlmostEqual(float(media_box.group(2)), 72.0)
            self.assertIn(b"/Width 600", result.read_bytes())
            self.assertIn(b"/Height 600", result.read_bytes())

    def test_pclm_is_preserved_as_pdf_without_external_converter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.prn"
            content = b"%PDF-1.3\n% PCLm 1.0\n1 0 obj\n%%EOF\n"
            source.write_bytes(content)
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            with patch("gadget_msc_printer.pdf_converter.subprocess.run") as run:
                result = converter.convert(source, "print")

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.read_bytes(), content)
            run.assert_not_called()

    def test_pwg_raster_uses_fixed_cups_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.prn"
            source.write_bytes(b"RaS2PwgRaster\x00" + b"\x00" * 128)
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            def convert(command, **kwargs):
                kwargs["stdout"].write(b"%PDF-1.7\n%%EOF\n")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    side_effect=lambda command: PWG_TO_PDF if command == PWG_TO_PDF else None,
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=convert,
                ) as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result, converter.last_error)
            command = run.call_args.args[0]
            self.assertEqual(command[0], PWG_TO_PDF)
            self.assertEqual(command[-1], str(source))

    def test_cups_raster_uses_fixed_cups_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.prn"
            source.write_bytes(b"3SaR" + b"\x00" * 128)
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            def convert(command, **kwargs):
                kwargs["stdout"].write(b"%PDF-1.7\n%%EOF\n")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value=PWG_TO_PDF,
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=convert,
                ) as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result, converter.last_error)
            self.assertEqual(run.call_args.args[0][0], PWG_TO_PDF)

    def test_pwg_filter_success_without_pdf_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.prn"
            source.write_bytes(b"RaS2PwgRaster\x00" + b"\x00" * 128)
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            def convert(command, **kwargs):
                kwargs["stdout"].write(b"not a PDF")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value=PWG_TO_PDF,
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=convert,
                ),
            ):
                result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertIn("could not convert PWG Raster", converter.last_error)
            self.assertEqual(list((root / "pdf").glob("*.pdf")), [])


    def test_apple_urf_uses_fixed_cups_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.prn"
            source.write_bytes(b"UNIRAST\x00" + b"\x00" * 128)
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            def convert(command, **kwargs):
                kwargs["stdout"].write(b"%PDF-1.7\n%%EOF\n")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value=PWG_TO_PDF,
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=convert,
                ) as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result, converter.last_error)
            self.assertEqual(run.call_args.args[0][0], PWG_TO_PDF)

    def test_multiframe_tiff_and_dcx_keep_every_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            white = Image.new("1", (16, 16), 1)
            black = Image.new("1", (16, 16), 0)
            try:
                tiff = root / "two-pages-tiff.prn"
                white.save(tiff, "TIFF", save_all=True, append_images=[black])
                dcx = root / "two-pages-dcx.prn"
                write_dcx(dcx, [white, black])
            finally:
                white.close()
                black.close()

            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
            for source in (tiff, dcx):
                with self.subTest(source=source.name):
                    result = converter.convert(source, "print")
                    self.assertIsNotNone(result, converter.last_error)
                    assert result is not None
                    self.assertEqual(len(re.findall(rb"/Type /Page\b", result.read_bytes())), 2)

    def test_known_corrupt_image_is_not_rendered_as_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "broken.prn"
            source.write_bytes(b"\x89PNG\r\n\x1a\nprintable-but-invalid")
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertIn("PNG could not be converted", converter.last_error)

    def test_multiframe_image_page_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "too-many-pages.prn"
            pages = [Image.new("1", (1, 1), index % 2) for index in range(101)]
            try:
                pages[0].save(source, "TIFF", save_all=True, append_images=pages[1:])
            finally:
                for page in pages:
                    page.close()
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertIn("invalid page count: 101", converter.last_error)

    def test_pdf_copy_does_not_preserve_future_fat_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.pdf"
            content = b"%PDF-1.4\n(Pantum GDI UFRII CAPT PRINTREX)\n%%EOF\n"
            source.write_bytes(content)
            future = time.time() + 8 * 60 * 60
            os.utime(source, (future, future))
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            result = converter.convert(source, "msc")

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.read_bytes(), content)
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

    def test_missing_ghostpcl_does_not_render_pcl_as_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.pcl"
            source.write_bytes(b"\x1bE\x1b*t300Rplain-looking-pcl\x0c\x1bE")
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf"), ghostpcl=[]))

            result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertIn("GhostPCL", converter.last_error)

    def test_pure_hpgl_uses_ghostpcl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "plot.prn"
            source.write_bytes(b"IN;SP1;PA100,100;PD500,100,500,500;PU;SP0;")
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            def convert(command, **kwargs):
                del kwargs
                output = next(
                    item.split("=", 1)[1]
                    for item in command
                    if item.startswith("-sOutputFile=")
                )
                Path(output).write_bytes(b"%PDF-1.7\n%%EOF\n")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/local/bin/gpcl6",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=convert,
                ) as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result)
            self.assertEqual(Path(run.call_args.args[0][0]).name, "gpcl6")

    def test_xps_uses_ghostxps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.prn"
            write_xps(source)
            converter = PdfConverter(
                PdfConfig(output_dir=str(root / "pdf"), xps_converters=["gxps"])
            )

            def convert(command, **kwargs):
                del kwargs
                output = next(
                    item.split("=", 1)[1]
                    for item in command
                    if item.startswith("-sOutputFile=")
                )
                Path(output).write_bytes(b"%PDF-1.7\n%%EOF\n")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/local/bin/gxps",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=convert,
                ) as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result)
            self.assertEqual(Path(run.call_args.args[0][0]).name, "gxps")

    def test_xps_prefers_xpstopdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.xps"
            write_xps(source)
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            def convert(command, **kwargs):
                del kwargs
                Path(command[2]).write_bytes(b"%PDF-1.7\n%%EOF\n")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    side_effect=lambda command: (
                        "/usr/bin/xpstopdf" if command == "xpstopdf" else None
                    ),
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=convert,
                ) as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result)
            command = run.call_args.args[0]
            self.assertEqual(command[0], "/usr/bin/xpstopdf")
            self.assertEqual(command[1], str(source))

    def test_escp2_uses_optional_escapy_converter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.prn"
            source.write_bytes(
                b"\x1b@\x1b(G\x01\x00\x01\x1b(U\x01\x00\x0a\x0c"
            )
            converter = PdfConverter(
                PdfConfig(
                    output_dir=str(root / "pdf"),
                    escp_converters=["escapy"],
                    escp2_profile="generic",
                )
            )

            def convert(command, **kwargs):
                self.assertIn("cwd", kwargs)
                output = Path(command[command.index("-o") + 1])
                output.write_bytes(b"%PDF-1.7\n%%EOF\n")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/bin/escapy",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=convert,
                ) as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result)
            command = run.call_args.args[0]
            self.assertEqual(command[0], "/usr/bin/escapy")
            self.assertNotIn("--pins", command)

    def test_escp2_uses_only_an_installed_whitelisted_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.prn"
            source.write_bytes(
                b"\x1b@\x1b(G\x01\x00\x01\x1b(U\x01\x00\x0a\x0c"
            )
            profile = root / "profiles" / "xp410" / "escapy.conf"
            profile.parent.mkdir(parents=True)
            profile.write_text("[misc]\n", encoding="ascii")
            converter = PdfConverter(
                PdfConfig(
                    output_dir=str(root / "pdf"),
                    escp_converters=["escapy"],
                    escp2_profile="xp410",
                )
            )

            def convert(command, **kwargs):
                del kwargs
                Path(command[command.index("-o") + 1]).write_bytes(
                    b"%PDF-1.7\n%%EOF\n"
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.ESCAPY_PROFILE_CONFIG_ROOT",
                    root / "profiles",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/bin/escapy",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=convert,
                ) as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--config") + 1], str(profile))

    def test_escp2_rejects_a_missing_non_generic_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.prn"
            source.write_bytes(
                b"\x1b@\x1b(G\x01\x00\x01\x1b(U\x01\x00\x0a\x0c"
            )
            converter = PdfConverter(
                PdfConfig(
                    output_dir=str(root / "pdf"),
                    escp_converters=["escapy"],
                    escp2_profile="xp410",
                )
            )
            with (
                patch(
                    "gadget_msc_printer.pdf_converter.ESCAPY_PROFILE_CONFIG_ROOT",
                    root / "missing",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/bin/escapy",
                ),
                patch("gadget_msc_printer.pdf_converter.subprocess.run") as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertIn("xp410", converter.last_error)
            run.assert_not_called()

    def test_escp2_auto_selects_only_validated_profile_fingerprints(self) -> None:
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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for profile in samples:
                config_path = root / "profiles" / profile / "escapy.conf"
                config_path.parent.mkdir(parents=True)
                config_path.write_text("[misc]\n", encoding="ascii")

            def convert(command, **kwargs):
                del kwargs
                Path(command[command.index("-o") + 1]).write_bytes(
                    b"%PDF-1.7\n%%EOF\n"
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            for expected, content in samples.items():
                with self.subTest(expected=expected):
                    source = root / f"{expected}.prn"
                    source.write_bytes(content)
                    converter = PdfConverter(
                        PdfConfig(
                            output_dir=str(root / f"pdf-{expected}"),
                            escp_converters=["escapy"],
                            escp2_profile="auto",
                        )
                    )
                    with (
                        patch(
                            "gadget_msc_printer.pdf_converter.ESCAPY_PROFILE_CONFIG_ROOT",
                            root / "profiles",
                        ),
                        patch(
                            "gadget_msc_printer.pdf_converter.shutil.which",
                            return_value="/usr/bin/escapy",
                        ),
                        patch(
                            "gadget_msc_printer.pdf_converter.subprocess.run",
                            side_effect=convert,
                        ) as run,
                    ):
                        result = converter.convert(source, "print")

                    self.assertIsNotNone(result)
                    self.assertEqual(converter.last_escp2_profile, expected)
                    command = run.call_args.args[0]
                    self.assertIn(
                        str(root / "profiles" / expected / "escapy.conf"), command
                    )

    def test_escp2_auto_retains_an_unknown_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "unknown-escp2.prn"
            source.write_bytes(
                b"\x1b@\x1b(G\x01\x00\x01\x1b(U\x01\x00\x0a\x0c"
            )
            converter = PdfConverter(
                PdfConfig(
                    output_dir=str(root / "pdf"),
                    escp_converters=["escapy"],
                    escp2_profile="auto",
                )
            )
            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/bin/escapy",
                ),
                patch("gadget_msc_printer.pdf_converter.subprocess.run") as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertEqual(converter.last_outcome, "retained")
            self.assertIn("严格自动匹配失败", converter.last_error)
            self.assertEqual(converter.last_escp2_profile, "")
            run.assert_not_called()

    def test_classic_escp_uses_configured_pin_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "dot-matrix.prn"
            source.write_bytes(
                b"\x1b@\x1bP\x1b3\x18\x1b*\x00\x01\x00\x80\x0c"
            )
            converter = PdfConverter(
                PdfConfig(
                    output_dir=str(root / "pdf"),
                    escp_converters=["escapy"],
                    escp_pins=9,
                )
            )

            def convert(command, **kwargs):
                del kwargs
                Path(command[command.index("-o") + 1]).write_bytes(
                    b"%PDF-1.7\n%%EOF\n"
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/bin/escapy",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=convert,
                ) as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--pins") + 1], "9")

    def test_escapy_input_removes_only_terminal_form_feed(self) -> None:
        samples = {
            "single-page": (
                b"page one\r\n\x0c\x1b@\r\n\x1b%-12345X",
                b"page one\r\n\x1b@\r\n\x1b%-12345X",
            ),
            "multi-page": (
                b"page one\x0cpage two\x0c\x1b@",
                b"page one\x0cpage two\x1b@",
            ),
            "explicit-blank-page": (
                b"page one\x0c\x0c\x1b@",
                b"page one\x0c\x1b@",
            ),
            "epson-remote-job-end": (
                b"page one\r\x0c\x1b@"
                b"\x1b(R\x08\x00\x00REMOTE1"
                b"LD\x00\x00JE\x01\x00\x00\x1b\x00\x00\x00",
                b"page one\r\x1b@"
                b"\x1b(R\x08\x00\x00REMOTE1"
                b"LD\x00\x00JE\x01\x00\x00\x1b\x00\x00\x00",
            ),
            "epson-r800-remote-job-end": (
                b"page one\r\x0c\x1b@"
                b"\x1b(R\x08\x00\x00REMOTE1"
                b"IR\x02\x00\x00\x00LD\x00\x00JE\x01\x00\x00"
                b"\x1b\x00\x00\x00",
                b"page one\r\x1b@"
                b"\x1b(R\x08\x00\x00REMOTE1"
                b"IR\x02\x00\x00\x00LD\x00\x00JE\x01\x00\x00"
                b"\x1b\x00\x00\x00",
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, (content, expected) in samples.items():
                with self.subTest(name=name):
                    source = root / f"{name}.prn"
                    source.write_bytes(content)
                    work = root / f"{name}-work"
                    work.mkdir()
                    prepared = PdfConverter._prepare_escapy_source(source, work)
                    self.assertEqual(prepared.read_bytes(), expected)
                    self.assertEqual(source.read_bytes(), content)

    def test_escapy_input_keeps_non_terminal_form_feed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "continued.prn"
            content = b"page one\x0c\x1b@next page data"
            source.write_bytes(content)

            prepared = PdfConverter._prepare_escapy_source(source, root / "unused")

            self.assertEqual(prepared, source)
            self.assertEqual(source.read_bytes(), content)

    def test_escapy_input_keeps_form_feed_before_invalid_remote_trailer(self) -> None:
        samples = {
            "unknown-command": (
                b"page one\x0c\x1b(R\x08\x00\x00REMOTE1"
                b"ZZ\x00\x00\x1b\x00\x00\x00"
            ),
            "invalid-length": (
                b"page one\x0c\x1b(R\x08\x00\x00REMOTE1"
                b"IR\x03\x00\x00\x00\x00\x1b\x00\x00\x00"
            ),
            "continued-page-data": b"page one\x0c\x1b@next page data",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in samples.items():
                with self.subTest(name=name):
                    source = root / f"{name}.prn"
                    source.write_bytes(content)
                    prepared = PdfConverter._prepare_escapy_source(
                        source, root / "unused"
                    )
                    self.assertEqual(prepared, source)
                    self.assertEqual(source.read_bytes(), content)

    def test_pcl3gui_and_escpr_are_not_sent_to_other_interpreters(self) -> None:
        samples = {
            "pcl3gui": b"@PJL ENTER LANGUAGE=PCL3GUI\r\nprivate",
            "escpr": b"@EJL JOB\r\nESC/P-R raster payload",
            "sharp_splc": b"SHARP CORPORATION\n@PJL ENTER LANGUAGE=SPLC\nprivate",
            "zpl": b"^XA\n^FO20,20^FDReport^FS\n^XZ",
            "ibm_afp": (
                b"\x5a\x00\x09\xd3\xa8\x00\x00\x00\x01"
                b"\x5a\x00\x09\xd3\xa8\x00\x00\x00\x02"
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
            with patch("gadget_msc_printer.pdf_converter.subprocess.run") as run:
                for name, content in samples.items():
                    with self.subTest(name=name):
                        source = root / f"{name}.prn"
                        source.write_bytes(content)
                        self.assertIsNone(converter.convert(source, "print"))
                        self.assertEqual(
                            converter.last_outcome,
                            "failed" if name == "escpr" else "retained",
                        )
                        if name != "escpr":
                            self.assertIn("保留原始PRN", converter.last_error)
            run.assert_not_called()

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

    def test_private_raster_protocols_use_their_offline_decoders(self) -> None:
        samples = {
            "spl": (b"\x1b%-12345X@PJL ENTER LANGUAGE = QPDL\r\nprivate", "qpdldecode"),
            "xqx": (b"\x1b%-12345X@PJL JOB\r\n,XQXprivate", "xqxdecode"),
            "hiperc": (b"\x1b%-12345X@PJL ENTER LANGUAGE=HIPERC\r\nprivate", "hipercdecode"),
            "ddst": (
                b"@PJL SET COMPRESS=JBIG\r\n@PJL SET PAGESTATUS=START\r\n"
                b"@PJL SET IMAGELEN=12\r\nprivate",
                "ddstdecode",
            ),
            "lavaflow": (
                b"@PJL ENTER LANGUAGE=LAVAFLOW\r\nprivate",
                "lavadecode",
            ),
            "opl": (
                b"Event=StartOfJob;RasterObject.Compression=JBIG;private",
                "opldecode",
            ),
            "slx": (b"\xa5SLX\x00\x00private", "slxdecode"),
            "oakt": (b"PJL preamble\r\nOAKTprivate", "oakdecode"),
            "brother_hbp": (
                b"@PJL SET RAS1200MODE = FALSE\r\n@PJL ENTER LANGUAGE = PCL\r\n"
                b"\x1bE\x1b*b1030m3w\x00\x01\x02",
                "brdecode",
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
            commands: list[str] = []

            def decode(command, **kwargs):
                del kwargs
                decoder = Path(command[0]).name
                commands.append(decoder)
                black_plane = {
                    "hipercdecode": 3,
                    "lavadecode": 1,
                    "opldecode": 1,
                    "slxdecode": 1,
                    "oakdecode": 3,
                }.get(decoder, 4)
                suffix = f"-{black_plane}-0" if decoder == "oakdecode" else f"-{black_plane}"
                if decoder == "brdecode":
                    self.assertEqual(Path(command[1]).name, "stream.brother_hbp")
                    Path(f"{command[2]}-1.pbm").write_bytes(b"P4\n8 1\n\x00")
                else:
                    Path(f"{command[2]}-01{suffix}.pbm").write_bytes(b"P4\n8 1\n\x00")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    side_effect=lambda command: f"/usr/bin/{command}",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    side_effect=decode,
                ),
            ):
                for protocol, (content, expected_decoder) in samples.items():
                    with self.subTest(protocol=protocol):
                        source = root / f"{protocol}.prn"
                        source.write_bytes(content)
                        result = converter.convert(source, "print")
                        self.assertIsNotNone(result)
                        self.assertEqual(commands[-1], expected_decoder)

    def test_gipd_is_retained_without_running_structure_only_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "gipd.prn"
            source.write_bytes(b"offset-table GDIJprivate GDIPpage")
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            with patch("gadget_msc_printer.pdf_converter.subprocess.run") as run:
                result = converter.convert(source, "print")

            self.assertIsNone(result)
            run.assert_not_called()
            self.assertEqual(converter.last_outcome, "retained")
            self.assertIn("识别为Granite GIPD", converter.last_error)
            self.assertIn("保留原始PRN", converter.last_error)

    def test_private_raster_color_planes_are_combined_as_cmyk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            planes: dict[tuple[int | None, int | None], Path] = {}
            for plane_number in (1, 2, 3, 4):
                path = root / f"page-01-{plane_number}.pbm"
                Image.new("1", (8, 8), 0 if plane_number == 1 else 1).save(path)
                planes[(plane_number, None)] = path
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            spec = private_raster_spec("spl")
            assert spec is not None
            page = converter._compose_private_page(planes, 1, "qpdldecode", spec)

            self.assertIsNotNone(page)
            assert page is not None
            try:
                red, green, blue = page.getpixel((0, 0))
                self.assertLess(red, 20)
                self.assertGreater(green, 235)
                self.assertGreater(blue, 235)
            finally:
                page.close()

    def test_private_raster_decoder_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "qpdl.prn"
            source.write_bytes(b"@PJL ENTER LANGUAGE=QPDL\r\nprivate")
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/bin/qpdldecode",
                ),
                patch(
                    "gadget_msc_printer.pdf_converter.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        ["qpdldecode"], 2, "", "invalid page record"
                    ),
                ),
            ):
                result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertIn("exit code 2", converter.last_error)
            self.assertIn("invalid page record", converter.last_error)

    def test_hbpl_requires_the_isolated_audited_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "hbpl.prn"
            source.write_bytes(b"@PJL ENTER LANGUAGE=HBPL\r\nprivate")
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
            with (
                patch("gadget_msc_printer.pdf_converter.shutil.which", return_value=None),
                patch("gadget_msc_printer.pdf_converter.subprocess.run") as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertIn("/usr/local/libexec/jvlei-prn-decoders/hbpldecode", converter.last_error)
            run.assert_not_called()

    def test_ddst_requires_the_isolated_audited_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "ddst.prn"
            source.write_bytes(
                b"@PJL SET COMPRESS=JBIG\r\n@PJL SET PAGESTATUS=START\r\n"
                b"@PJL SET IMAGELEN=12\r\nprivate"
            )
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
            with (
                patch("gadget_msc_printer.pdf_converter.shutil.which", return_value=None),
                patch("gadget_msc_printer.pdf_converter.subprocess.run") as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertIn(
                "/usr/local/libexec/jvlei-prn-decoders/ddstdecode", converter.last_error
            )
            run.assert_not_called()

    def test_opl_and_slx_require_the_isolated_audited_decoders(self) -> None:
        samples = {
            "opl": (
                b"Event=StartOfJob;RasterObject.Compression=JBIG;private",
                "/usr/local/libexec/jvlei-prn-decoders/opldecode",
            ),
            "slx": (
                b"\xa5SLX\x00\x00private",
                "/usr/local/libexec/jvlei-prn-decoders/slxdecode",
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for protocol, (content, expected) in samples.items():
                with self.subTest(protocol=protocol):
                    source = root / f"{protocol}.prn"
                    source.write_bytes(content)
                    converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
                    with (
                        patch(
                            "gadget_msc_printer.pdf_converter.shutil.which",
                            return_value=None,
                        ),
                        patch("gadget_msc_printer.pdf_converter.subprocess.run") as run,
                    ):
                        result = converter.convert(source, "print")

                    self.assertIsNone(result)
                    self.assertIn(expected, converter.last_error)
                    run.assert_not_called()

    def test_audited_hbpl_v1_page_image_is_converted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "hbpl.prn"
            source.write_bytes(b"@PJL ENTER LANGUAGE=HBPL\r\nprivate")
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))

            def decode(command, **kwargs):
                del kwargs
                Image.new("RGB", (8, 8), (10, 20, 30)).save(f"{command[2]}-01.ppm")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "gadget_msc_printer.pdf_converter.shutil.which",
                    return_value="/usr/local/libexec/jvlei-prn-decoders/hbpldecode",
                ),
                patch("gadget_msc_printer.pdf_converter.subprocess.run", side_effect=decode),
            ):
                result = converter.convert(source, "print")

            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.read_bytes().startswith(b"%PDF-"))

    def test_brother_hbp_requires_the_isolated_audited_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "brother-hbp.prn"
            source.write_bytes(
                b"@PJL SET RAS1200MODE = FALSE\r\n@PJL ENTER LANGUAGE = PCL\r\n"
                b"\x1bE\x1b*b1030m3w\x00\x01\x02"
            )
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
            with (
                patch("gadget_msc_printer.pdf_converter.shutil.which", return_value=None),
                patch("gadget_msc_printer.pdf_converter.subprocess.run") as run,
            ):
                result = converter.convert(source, "print")

            self.assertIsNone(result)
            self.assertIn(
                "/usr/local/libexec/jvlei-prn-decoders/brdecode", converter.last_error
            )
            run.assert_not_called()

    def test_oakt_two_bit_subplanes_are_reconstructed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            low = root / "page-01-3-0.pbm"
            high = root / "page-01-3-1.pbm"
            low_image = Image.new("1", (4, 1), 1)
            high_image = Image.new("1", (4, 1), 1)
            low_image.putdata([1, 0, 0, 1])
            high_image.putdata([1, 1, 0, 0])
            low_image.save(low)
            high_image.save(high)
            low_image.close()
            high_image.close()
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
            spec = private_raster_spec("oakt")
            assert spec is not None

            page = converter._compose_private_page(
                {(3, 0): low, (3, 1): high}, 1, "oakdecode", spec
            )

            self.assertIsNotNone(page)
            assert page is not None
            try:
                values = [page.getpixel((index, 0))[0] for index in range(4)]
                self.assertEqual(values[0], 255)
                self.assertTrue(145 <= values[1] <= 160)
                self.assertTrue(70 <= values[2] <= 85)
                self.assertEqual(values[3], 0)
            finally:
                page.close()

    def test_private_page_stream_transform_is_applied(self) -> None:
        image = Image.new("RGB", (2, 1), "white")
        image.putpixel((0, 0), (0, 0, 0))
        mirrored = PdfConverter._apply_private_page_transform(image, "mirror_horizontal")
        try:
            self.assertEqual(mirrored.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(mirrored.getpixel((1, 0)), (0, 0, 0))
        finally:
            mirrored.close()

        image = Image.new("RGB", (2, 1), "white")
        image.putpixel((0, 0), (0, 0, 0))
        rotated = PdfConverter._apply_private_page_transform(image, "rotate_90")
        try:
            self.assertEqual(rotated.size, (1, 2))
            self.assertEqual(rotated.getpixel((0, 1)), (0, 0, 0))
        finally:
            rotated.close()

    def test_oakt_color_plane_order_is_yellow_magenta_cyan_black(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            planes: dict[tuple[int | None, int | None], Path] = {}
            for plane_number in range(4):
                path = root / f"page-01-{plane_number}.pbm"
                Image.new("1", (2, 2), 0 if plane_number == 0 else 1).save(path)
                planes[(plane_number, None)] = path
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
            spec = private_raster_spec("oakt")
            assert spec is not None

            page = converter._compose_private_page(planes, 1, "oakdecode", spec)

            self.assertIsNotNone(page)
            assert page is not None
            try:
                red, green, blue = page.getpixel((0, 0))
                self.assertGreater(red, 235)
                self.assertGreater(green, 235)
                self.assertLess(blue, 20)
            finally:
                page.close()

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
