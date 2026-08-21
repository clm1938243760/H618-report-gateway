from __future__ import annotations

import struct
import unittest

from gadget_msc_printer.private_raster import (
    private_raster_dpi,
    private_raster_spec,
    private_raster_transform,
)


def xqx_item(item_type: int, value: int) -> bytes:
    return struct.pack(">III", item_type, 4, value)


class PrivateRasterMetadataTests(unittest.TestCase):
    def test_gipd_is_recognized_but_structure_only_decoder_is_disabled(self) -> None:
        spec = private_raster_spec("gipd")

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertFalse(spec.enabled)
        self.assertIn("只输出结构", spec.disabled_reason)
        self.assertIn("不能导出页面", spec.disabled_reason)

    def test_qpdl_page_header_reports_asymmetric_resolution(self) -> None:
        page_header = bytearray(16)
        page_header[0] = 6
        page_header[14:16] = (12).to_bytes(2, "big")
        stream = (
            b"\x1b%-12345X@PJL ENTER LANGUAGE = QPDL\r\n"
            + b"\x00"
            + bytes(page_header)
        )

        self.assertEqual(private_raster_dpi(stream, "spl"), (1200, 600))

    def test_xqx_accounts_for_decoder_bit_plane_width(self) -> None:
        page = b"".join(
            (
                xqx_item(0x20000008, 600),
                xqx_item(0x20000009, 600),
                xqx_item(0x2000000A, 2),
            )
        )
        stream = b",XQX" + struct.pack(">II", 3, 3) + page

        self.assertEqual(private_raster_dpi(stream, "xqx"), (1200, 600))

    def test_xqx_one_bit_mode_remains_square_resolution(self) -> None:
        page = b"".join(
            (
                xqx_item(0x20000008, 600),
                xqx_item(0x20000009, 600),
                xqx_item(0x2000000A, 1),
            )
        )
        stream = b",XQX" + struct.pack(">II", 3, 3) + page

        self.assertEqual(private_raster_dpi(stream, "xqx"), (600, 600))

    def test_hiperc_vertical_resolution_is_read_from_v_setting(self) -> None:
        stream = (
            b"@PJL SET RESOLUTION=600\r\n"
            b"@PJL SET RESOLUTION=V1200\r\n"
            b"@PJL ENTER LANGUAGE=HIPERC\n"
        )

        self.assertEqual(private_raster_dpi(stream, "hiperc"), (600, 1200))

    def test_hbpl_accounts_for_packed_horizontal_samples(self) -> None:
        stream = (
            b"@PJL SET RESOLUTION=600\r\n"
            b"@PJL SET BITSPERPIXEL=2\r\n"
            b"@PJL ENTER LANGUAGE=HBPL\r\n"
        )

        self.assertEqual(private_raster_dpi(stream, "hbpl"), (1200, 600))

    def test_lavaflow_reads_binary_resolution_header(self) -> None:
        stream = (
            b"@PJL ENTER LANGUAGE=LAVAFLOW\r\n"
            b"\x1b&u1200D"
            b"\x1b*g8W\x02\x01\x04\xb0\x02\x58\x00\x02"
        )

        self.assertEqual(private_raster_dpi(stream, "lavaflow"), (1200, 600))

    def test_opl_reads_text_resolution(self) -> None:
        stream = (
            b"Event=StartOfJob;OSVersion=Linux;Resolution=1200x600;"
            b"RasterObject.Compression=JBIG;"
        )

        self.assertEqual(private_raster_dpi(stream, "opl"), (1200, 600))

    def test_slx_reads_start_page_resolution_items(self) -> None:
        def item(code: int, value: int) -> bytes:
            return struct.pack(">IHBBI", 12, code, 1, 0, value)

        start_doc = struct.pack(">IIIHH", 16, 0, 0, 0, 0xA5A5)
        items = item(0x105, 1200) + item(0x106, 600)
        start_page = struct.pack(">IIIHH", 16 + len(items), 2, 2, 0, 0xA5A5) + items
        stream = b"\xa5SLX" + start_doc + start_page

        self.assertEqual(private_raster_dpi(stream, "slx"), (1200, 600))

    def test_oakt_reads_little_endian_page_resolution_record(self) -> None:
        page = struct.pack("<11I", 0, 1, 4800, 6814, 600, 600, 1, 0, 0, 0, 0)
        stream = b"OAKT" + struct.pack("<II", 12 + len(page), 0x33) + page

        self.assertEqual(private_raster_dpi(stream, "oakt"), (600, 600))

    def test_oakt_uses_stream_orientation_for_model_transform(self) -> None:
        def record(record_type: int, payload: bytes) -> bytes:
            return b"OAKT" + struct.pack("<II", 12 + len(payload), record_type) + payload

        page = struct.pack("<11I", 0, 1, 4800, 6814, 600, 600, 1, 0, 0, 0, 0)
        hp_paper = struct.pack("<5I", 9, 9920, 14028, 0, 0)
        kyocera_paper = struct.pack("<5I", 9, 7014, 4960, 1, 0)

        self.assertEqual(
            private_raster_transform(record(0x2B, hp_paper) + record(0x33, page), "oakt"),
            "mirror_horizontal",
        )
        self.assertEqual(
            private_raster_transform(
                record(0x2B, kyocera_paper) + record(0x33, page), "oakt"
            ),
            "rotate_90",
        )

    def test_binary_resolution_parsers_reject_truncated_records(self) -> None:
        self.assertIsNone(private_raster_dpi(b"\xa5SLX\x00\x00\x10\x00", "slx"))
        self.assertIsNone(private_raster_dpi(b"OAKT\xff\xff\xff\x7f", "oakt"))

    def test_invalid_or_incomplete_metadata_is_not_trusted(self) -> None:
        self.assertIsNone(private_raster_dpi(b",XQX\x00", "xqx"))
        self.assertIsNone(
            private_raster_dpi(b"@PJL SET RESOLUTION=99999\r\n", "hiperc")
        )


if __name__ == "__main__":
    unittest.main()
