from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gadget_msc_printer.config import PdfConfig
from gadget_msc_printer.escpr import ESCPR_MODE, EscprDecodeError, decode_escpr
from gadget_msc_printer.pdf_converter import PdfConverter


def escpr_command(command_class: bytes, name: bytes, payload: bytes = b"") -> bytes:
    return b"\x1b" + command_class + len(payload).to_bytes(4, "little") + name + payload


def job_payload(
    width: int,
    height: int,
    dpi_code: int = 0,
    top_margin: int = 0,
    left_margin: int = 0,
) -> bytes:
    return (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + top_margin.to_bytes(2, "big")
        + left_margin.to_bytes(2, "big")
        + (width - left_margin).to_bytes(4, "big")
        + (height - top_margin).to_bytes(4, "big")
        + bytes((dpi_code, 0))
    )


def literal_raster(x: int, y: int, pixels: bytes) -> bytes:
    if not pixels or len(pixels) % 3 or len(pixels) // 3 > 128:
        raise ValueError("test raster must contain 1-128 RGB pixels")
    encoded = bytes((len(pixels) // 3 - 1,)) + pixels
    payload = (
        x.to_bytes(2, "big")
        + y.to_bytes(2, "big")
        + b"\x01"
        + len(encoded).to_bytes(2, "big")
        + encoded
    )
    return escpr_command(b"d", b"dsnd", payload)


def repeated_raster(x: int, y: int, count: int, pixel: bytes) -> bytes:
    if not 2 <= count <= 129 or len(pixel) != 3:
        raise ValueError("invalid test repeat")
    encoded = bytes((257 - count,)) + pixel
    payload = (
        x.to_bytes(2, "big")
        + y.to_bytes(2, "big")
        + b"\x01"
        + len(encoded).to_bytes(2, "big")
        + encoded
    )
    return escpr_command(b"d", b"dsnd", payload)


def make_job(*page_commands: bytes, width: int = 8, height: int = 6) -> bytes:
    setup = (
        b"\x00\x00\x00"
        + ESCPR_MODE
        + escpr_command(b"q", b"setq", b"\x00\x01\x00\x00\x00\x00\x00\x00\x00")
        + escpr_command(b"j", b"setj", job_payload(width, height))
    )
    pages = b"".join(
        escpr_command(b"p", b"sttp")
        + commands
        + escpr_command(b"p", b"endp", b"\x00")
        for commands in page_commands
    )
    return setup + pages + escpr_command(b"j", b"endj") + b"ignored trailer"


class EscprDecoderTests(unittest.TestCase):
    def test_decodes_full_color_rle_page(self) -> None:
        colors = b"\xff\x00\x00\x00\xff\x00\x00\x00\xff\xff\xff\xff"
        content = make_job(literal_raster(2, 3, colors))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "color.prn"
            source.write_bytes(content)
            document = decode_escpr(source)
        try:
            self.assertEqual(document.dpi, 360)
            self.assertEqual(document.pages[0].size, (8, 6))
            self.assertEqual(document.pages[0].getpixel((2, 3)), (255, 0, 0))
            self.assertEqual(document.pages[0].getpixel((3, 3)), (0, 255, 0))
            self.assertEqual(document.pages[0].getpixel((4, 3)), (0, 0, 255))
            self.assertEqual(document.pages[0].getpixel((0, 0)), (255, 255, 255))
        finally:
            document.close()

    def test_decodes_multiple_pages_and_uncompressed_raster(self) -> None:
        raw = b"\x00\x00\x00" * 3
        payload = b"\x00\x01\x00\x02\x00" + len(raw).to_bytes(2, "big") + raw
        uncompressed = escpr_command(b"d", b"dsnd", payload)
        content = make_job(repeated_raster(0, 0, 4, b"\xff\x00\x00"), uncompressed)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "two-pages.prn"
            source.write_bytes(content)
            document = decode_escpr(source)
        try:
            self.assertEqual(len(document.pages), 2)
            self.assertEqual(document.pages[0].getpixel((3, 0)), (255, 0, 0))
            self.assertEqual(document.pages[1].getpixel((1, 2)), (0, 0, 0))
        finally:
            document.close()

    def test_raster_coordinates_are_relative_to_printable_area(self) -> None:
        content = make_job(literal_raster(1, 1, b"\x12\x34\x56"))
        content = content.replace(job_payload(8, 6), job_payload(8, 6, 0, 2, 3))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "margins.prn"
            source.write_bytes(content)
            document = decode_escpr(source)
        try:
            self.assertEqual(document.pages[0].getpixel((4, 3)), (0x12, 0x34, 0x56))
            self.assertEqual(document.pages[0].getpixel((1, 1)), (255, 255, 255))
        finally:
            document.close()

    def test_rejects_truncated_command_and_raster(self) -> None:
        valid = make_job(repeated_raster(0, 0, 4, b"\xff\xff\xff"))
        samples = {
            "command": valid[: valid.find(b"endj") - 4],
            "raster": valid.replace(b"\x00\x04\xfd\xff\xff\xff", b"\x00\x05\xfd\xff\xff\xff"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, content in samples.items():
                with self.subTest(name=name):
                    source = Path(directory) / f"{name}.prn"
                    source.write_bytes(content)
                    with self.assertRaises(EscprDecodeError):
                        decode_escpr(source)

    def test_rejects_raster_outside_page(self) -> None:
        content = make_job(repeated_raster(7, 0, 4, b"\xff\xff\xff"))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "outside.prn"
            source.write_bytes(content)
            with self.assertRaisesRegex(EscprDecodeError, "coordinates"):
                decode_escpr(source)

    def test_rejects_unsupported_palette_and_excessive_page(self) -> None:
        palette = make_job(repeated_raster(0, 0, 2, b"\x00\x00\x00")).replace(
            b"setq\x00\x01\x00\x00\x00\x00\x00\x00\x00",
            b"setq\x00\x01\x00\x00\x00\x00\x01\x00\x00",
        )
        oversized = make_job(width=10_000, height=10_000)
        with tempfile.TemporaryDirectory() as directory:
            for name, content in (("palette", palette), ("oversized", oversized)):
                with self.subTest(name=name):
                    source = Path(directory) / f"{name}.prn"
                    source.write_bytes(content)
                    with self.assertRaises(EscprDecodeError):
                        decode_escpr(source)

    def test_enforces_decoded_byte_limit(self) -> None:
        content = make_job(repeated_raster(0, 0, 4, b"\x00\x00\x00"))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "limit.prn"
            source.write_bytes(content)
            with (
                patch("gadget_msc_printer.escpr.MAX_DECODED_BYTES", 8),
                self.assertRaisesRegex(EscprDecodeError, "expansion|decoded raster"),
            ):
                decode_escpr(source)

    def test_pdf_converter_uses_internal_decoder(self) -> None:
        content = make_job(repeated_raster(0, 0, 8, b"\x20\x40\x80"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "epson.prn"
            source.write_bytes(content)
            converter = PdfConverter(PdfConfig(output_dir=str(root / "pdf")))
            result = converter.convert(source, "print")

            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.read_bytes().startswith(b"%PDF-"))
            self.assertEqual(source.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
