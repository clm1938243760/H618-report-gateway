from __future__ import annotations

import unittest
from unittest.mock import patch

from gadget_msc_printer.print_boundary import (
    ESCPR_REMOTE_END_TRAILER,
    PrintBoundaryDetector,
    UEL,
)


PCL_START = UEL + b"\x1bE\x1b*t300R\x1b*r1A"
PCL_END = b"\x1b*rC\x0c\x1bE" + UEL


def escpr_command(command_class: bytes, name: bytes, payload: bytes = b"") -> bytes:
    return b"\x1b" + command_class + len(payload).to_bytes(4, "little") + name + payload


def escpr_job(raster: bytes = b"page-raster") -> bytes:
    return (
        b"ESCPRLIB\x00\x1b(R\x06\x00\x00ESCPR"
        + escpr_command(b"q", b"setq", b"\x00\x01\x00\x00\x00\x00\x00\x00\x00")
        + escpr_command(b"j", b"setj", b"\x00" * 22)
        + escpr_command(b"p", b"sttp")
        + escpr_command(b"d", b"dsnd", raster)
        + escpr_command(b"p", b"endp", b"\x00")
        + escpr_command(b"j", b"endj")
        + ESCPR_REMOTE_END_TRAILER
    )


class PrintBoundaryDetectorTests(unittest.TestCase):
    def test_initial_uel_is_not_a_job_end_and_terminal_uel_is(self) -> None:
        detector = PrintBoundaryDetector()
        self.assertEqual(detector.feed(PCL_START, 1), [])
        events = detector.feed(b"page-data" + PCL_END, 2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].reason, "pcl_uel")
        self.assertEqual(events[0].protocol, "pcl")

    def test_uel_can_span_input_chunks(self) -> None:
        detector = PrintBoundaryDetector()
        detector.feed(PCL_START + b"page" + b"\x1b*rC\x0c\x1bE" + UEL[:4], 1)
        events = detector.feed(UEL[4:], 2)
        self.assertEqual([event.reason for event in events], ["pcl_uel"])

    def test_two_pcl_jobs_in_one_chunk_produce_two_boundaries(self) -> None:
        detector = PrintBoundaryDetector()
        job = PCL_START + b"page" + PCL_END
        events = detector.feed(job + job, 1)
        self.assertEqual([event.end_offset for event in events], [len(job), len(job) * 2])

    def test_uel_inside_declared_raster_payload_is_ignored(self) -> None:
        detector = PrintBoundaryDetector()
        binary = UEL + b"xyz"
        stream = PCL_START + f"\x1b*b{len(binary)}W".encode("ascii") + binary
        self.assertEqual(detector.feed(stream, 1), [])
        events = detector.feed(PCL_END, 2)
        self.assertEqual([event.reason for event in events], ["pcl_uel"])

    def test_pjl_eoj_and_final_uel_complete_wrapped_job(self) -> None:
        detector = PrintBoundaryDetector()
        stream = (
            UEL
            + b"@PJL JOB NAME=TEST\r\n"
            + b"@PJL ENTER LANGUAGE=PCL\r\n"
            + b"\x1bEpage\x1bE"
            + UEL
            + b"@PJL EOJ NAME=TEST\r\n"
            + UEL
        )
        events = detector.feed(stream, 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].reason, "pjl_eoj")
        self.assertEqual(events[0].end_offset, len(stream))

    def test_pclxl_pjl_wrapper_uses_final_boundary(self) -> None:
        detector = PrintBoundaryDetector()
        stream = (
            UEL
            + b"@PJL JOB\r\n@PJL ENTER LANGUAGE=PCLXL\r\n"
            + b") HP-PCL XL;2;0\r\nBinarySession"
            + UEL
            + b"@PJL EOJ\r\n"
            + UEL
        )
        events = detector.feed(stream, 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].protocol, "pclxl")
        self.assertEqual(events[0].reason, "pjl_eoj")

    def test_postscript_ctrl_d_is_immediate(self) -> None:
        detector = PrintBoundaryDetector()
        events = detector.feed(b"%!PS-Adobe-3.0\nshowpage\n\x04", 1)
        self.assertEqual([event.reason for event in events], ["postscript_ctrl_d"])

    def test_postscript_leading_ctrl_d_is_not_treated_as_the_end(self) -> None:
        detector = PrintBoundaryDetector()
        events = detector.feed(b"\x04%!PS-Adobe-3.0\nshowpage\n\x04", 1)
        self.assertEqual([event.reason for event in events], ["postscript_ctrl_d"])
        self.assertEqual(events[0].end_offset, len(b"\x04%!PS-Adobe-3.0\nshowpage\n\x04"))

    def test_postscript_eof_requires_grace_period(self) -> None:
        detector = PrintBoundaryDetector(grace_ns=200)
        self.assertEqual(detector.feed(b"%!PS\nshowpage\n%%EOF\n", 100), [])
        self.assertIsNone(detector.poll(299, 10_000))
        event = detector.poll(300, 10_000)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.reason, "postscript_eof")

    def test_pdf_eof_requires_grace_and_new_data_cancels_candidate(self) -> None:
        detector = PrintBoundaryDetector(grace_ns=200)
        detector.feed(b"%PDF-1.7\nbody\n%%EOF", 100)
        detector.feed(b"\nupdated", 150)
        self.assertIsNone(detector.poll(500, 10_000))
        detector.feed(b"\n%%EOF", 600)
        event = detector.poll(800, 10_000)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.reason, "pdf_eof")

    def test_pdf_header_and_eof_can_span_usb_reads(self) -> None:
        detector = PrintBoundaryDetector(grace_ns=200)

        detector.feed(b"\x00%PD", 100)
        detector.feed(b"F-1.7\nbody\n%%EO", 150)
        detector.feed(b"F", 200)
        event = detector.poll(400, 10_000)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.protocol, "pdf")
        self.assertEqual(event.reason, "pdf_eof")

    def test_vendor_words_inside_pdf_do_not_override_standard_protocol(self) -> None:
        detector = PrintBoundaryDetector(grace_ns=200)
        detector.feed(
            b"%PDF-1.7\n(Pantum GDI UFRII CAPT PRINTREX)\n%%EOF",
            100,
        )

        event = detector.poll(300, 10_000)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.protocol, "pdf")
        self.assertEqual(event.reason, "pdf_eof")

    def test_pclm_uses_pdf_eof_with_its_exact_protocol(self) -> None:
        detector = PrintBoundaryDetector(grace_ns=200)
        detector.feed(b"%PDF-1.3\n% PCLm 1.0\nbody\n%%EOF", 100)

        event = detector.poll(300, 10_000)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.protocol, "pclm")
        self.assertEqual(event.reason, "pclm_eof")

    def test_pwg_and_urf_are_identified_but_use_idle_timeout(self) -> None:
        samples = {
            "pwg_raster": b"RaS2PwgRaster\x00" + b"\x00" * 64,
            "cups_raster": b"3SaR" + b"\x00" * 64,
            "apple_urf": b"UNIRAST\x00" + b"\x00" * 64,
        }
        for expected, content in samples.items():
            with self.subTest(expected=expected):
                detector = PrintBoundaryDetector()
                detector.feed(content, 100)
                event = detector.poll(200, 100)
                self.assertIsNotNone(event)
                assert event is not None
                self.assertEqual(event.protocol, expected)
                self.assertEqual(event.reason, "idle_timeout")

    def test_binary_escpr_uses_structured_end_job_boundary(self) -> None:
        detector = PrintBoundaryDetector()
        stream = escpr_job()

        events = detector.feed(stream, 100)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].end_offset, len(stream))
        self.assertEqual(events[0].protocol, "escpr")
        self.assertEqual(events[0].reason, "escpr_endj")

    def test_escpr_boundary_and_trailer_can_span_input_chunks(self) -> None:
        detector = PrintBoundaryDetector()
        stream = escpr_job()
        split_points = (3, 19, 41, len(stream) - 7)
        start = 0
        events = []
        for end in (*split_points, len(stream)):
            events.extend(detector.feed(stream[start:end], end))
            start = end

        self.assertEqual([event.reason for event in events], ["escpr_endj"])

    def test_escpr_endj_inside_declared_raster_is_ignored(self) -> None:
        fake_end = escpr_command(b"j", b"endj") + ESCPR_REMOTE_END_TRAILER
        detector = PrintBoundaryDetector()
        stream = escpr_job(b"before" + fake_end + b"after")

        events = detector.feed(stream, 100)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].end_offset, len(stream))

    def test_two_escpr_jobs_in_one_chunk_produce_two_boundaries(self) -> None:
        detector = PrintBoundaryDetector()
        job = escpr_job()

        events = detector.feed(job + job, 100)

        self.assertEqual([event.reason for event in events], ["escpr_endj", "escpr_endj"])
        self.assertEqual([event.end_offset for event in events], [len(job), len(job) * 2])

    def test_escpr_raster_payload_is_consumed_in_bulk(self) -> None:
        detector = PrintBoundaryDetector()
        raster = (b"binary\x1b\x04%@" * (512 * 1024 // 10)) + b"tail"
        stream = escpr_job(raster)

        with patch.object(
            detector,
            "_consume_control_byte",
            wraps=detector._consume_control_byte,
        ) as consume_control:
            events = detector.feed(stream, 100)

        self.assertEqual([event.reason for event in events], ["escpr_endj"])
        self.assertLess(consume_control.call_count, 200)

    def test_escpr_endj_without_known_trailer_uses_short_grace(self) -> None:
        detector = PrintBoundaryDetector(grace_ns=200)
        stream = escpr_job()[: -len(ESCPR_REMOTE_END_TRAILER)]

        self.assertEqual(detector.feed(stream, 100), [])
        event = detector.poll(300, 10_000)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.protocol, "escpr")
        self.assertEqual(event.reason, "escpr_endj")

    def test_large_unknown_stream_is_not_reparsed_for_every_byte(self) -> None:
        detector = PrintBoundaryDetector()

        with patch(
            "gadget_msc_printer.print_boundary.detect_private_raster",
            return_value=None,
        ) as detect, patch.object(
            detector,
            "_consume_control_byte",
            wraps=detector._consume_control_byte,
        ) as consume_control:
            detector.feed(b"x" * (256 * 1024), 100)

        self.assertLess(detect.call_count, 20)
        self.assertLess(consume_control.call_count, 20)

    def test_declared_pcl_binary_payload_is_consumed_in_bulk(self) -> None:
        detector = PrintBoundaryDetector()
        binary = b"\x1b%@\x04" * (64 * 1024)
        stream = PCL_START + f"\x1b*b{len(binary)}W".encode("ascii") + binary + PCL_END

        with patch.object(
            detector,
            "_consume_control_byte",
            wraps=detector._consume_control_byte,
        ) as consume_control:
            events = detector.feed(stream, 100)

        self.assertEqual([event.reason for event in events], ["pcl_uel"])
        self.assertLess(consume_control.call_count, 200)

    def test_declared_pcl_binary_payload_can_span_usb_reads(self) -> None:
        detector = PrintBoundaryDetector()
        binary = b"\x1b%@\x04" * 1024
        command = f"\x1b*b{len(binary)}W".encode("ascii")

        self.assertEqual(detector.feed(PCL_START + command + binary[:123], 100), [])
        events = detector.feed(binary[123:] + PCL_END, 200)

        self.assertEqual([event.reason for event in events], ["pcl_uel"])
        self.assertEqual(events[0].protocol, "pcl")

    def test_pcl_control_bytes_do_not_trigger_full_protocol_rescans(self) -> None:
        detector = PrintBoundaryDetector()
        stream = PCL_START + (b"@\x04\x1bAdata" * 4096) + PCL_END

        with patch.object(
            detector,
            "_refresh_protocol_from_probe",
            wraps=detector._refresh_protocol_from_probe,
        ) as refresh:
            events = detector.feed(stream, 100)

        self.assertEqual([event.reason for event in events], ["pcl_uel"])
        self.assertLess(refresh.call_count, 30)

    def test_known_pcl_treats_at_and_ctrl_d_as_bulk_payload(self) -> None:
        detector = PrintBoundaryDetector()
        stream = PCL_START + (b"@\x04ordinary-data" * 4096) + PCL_END

        with patch.object(
            detector,
            "_consume_control_byte",
            wraps=detector._consume_control_byte,
        ) as consume_control:
            events = detector.feed(stream, 100)

        self.assertEqual([event.reason for event in events], ["pcl_uel"])
        self.assertLess(consume_control.call_count, 100)

    def test_gipd_after_large_offset_table_is_still_identified(self) -> None:
        detector = PrintBoundaryDetector()
        offset_record = b"\x00" * 124 + b"OFST"
        stream = offset_record * 1276 + b"GDIJ" + b"\x00" * 64 + b"GDIP"

        detector.feed(stream, 100)
        event = detector.poll(200, 100)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.protocol, "gipd")
        self.assertEqual(event.reason, "idle_timeout")


    def test_unknown_stream_uses_idle_timeout(self) -> None:
        detector = PrintBoundaryDetector()
        detector.feed(b"\x00vendor-private-data", 100)
        self.assertIsNone(detector.poll(199, 100))
        event = detector.poll(200, 100)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.reason, "idle_timeout")
        self.assertEqual(event.protocol, "unknown")

    def test_pure_hpgl_is_identified_and_uses_idle_timeout(self) -> None:
        detector = PrintBoundaryDetector()
        detector.feed(b"IN;SP1;PA100,100;PD500,100,500,500;PU;SP0;", 100)

        event = detector.poll(200, 100)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.protocol, "hpgl")
        self.assertEqual(event.reason, "idle_timeout")

    def test_hpgl_terminal_uel_is_an_immediate_boundary(self) -> None:
        detector = PrintBoundaryDetector()
        stream = UEL + b"\x1b%0BIN;SP1;PA100,100;PD500,500;PU;\x1b%0A" + UEL

        events = detector.feed(stream, 100)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].protocol, "hpgl")
        self.assertEqual(events[0].reason, "hpgl_uel")

    def test_zjstream_pjl_job_uses_eoj_boundary(self) -> None:
        detector = PrintBoundaryDetector()
        stream = (
            UEL
            + b"@PJL JOB\r\n"
            + b"JZJZbinary-page"
            + UEL
            + b"@PJL EOJ\r\n"
            + UEL
        )

        events = detector.feed(stream, 1)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].protocol, "zjstream")
        self.assertEqual(events[0].reason, "pjl_eoj")

    def test_pjl_uel_candidate_is_cancelled_when_private_payload_follows(self) -> None:
        detector = PrintBoundaryDetector()
        stream = (
            UEL
            + b"@PJL JOB\r\n"
            + UEL
            + b"JZJZ"
            + b"private-page" * 2048
            + UEL
            + b"@PJL EOJ\r\n"
            + UEL
        )

        with patch.object(
            detector,
            "_consume_control_byte",
            wraps=detector._consume_control_byte,
        ) as consume_control:
            events = detector.feed(stream, 100)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].protocol, "zjstream")
        self.assertEqual(events[0].reason, "pjl_eoj")
        self.assertEqual(events[0].end_offset, len(stream))
        self.assertLess(consume_control.call_count, 200)

    def test_private_pjl_languages_keep_their_protocol_at_eoj(self) -> None:
        languages = {
            b"QPDL": "spl",
            b"XQX": "xqx",
            b"HIPERC": "hiperc",
            b"HBPL": "hbpl",
            b"DDST": "ddst",
            b"LAVAFLOW": "lavaflow",
            b"OPL": "opl",
            b"SLX": "slx",
            b"OAKT": "oakt",
            b"GIPD": "gipd",
            b"HBP": "brother_hbp",
            b"XL2HB": "brother_hbp",
        }
        for language, expected in languages.items():
            with self.subTest(language=language):
                detector = PrintBoundaryDetector()
                stream = (
                    UEL
                    + b"@PJL JOB\r\n@PJL ENTER LANGUAGE="
                    + language
                    + b"\r\nprivate-page"
                    + UEL
                    + b"@PJL EOJ\r\n"
                    + UEL
                )

                events = detector.feed(stream, 1)

                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].protocol, expected)
                self.assertEqual(events[0].reason, "pjl_eoj")

    def test_brlaser_hbp_signature_overrides_declared_pcl(self) -> None:
        detector = PrintBoundaryDetector()
        stream = (
            UEL
            + b"@PJL JOB NAME=HBP\r\n"
            + b"@PJL SET RAS1200MODE = FALSE\r\n"
            + b"@PJL ENTER LANGUAGE = PCL\r\n"
            + b"\x1bE\x1b*b1030m3w\x00\x01\x02\x0c"
            + UEL
            + b"@PJL EOJ NAME=HBP\r\n"
            + UEL
        )

        events = detector.feed(stream, 1)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].protocol, "brother_hbp")
        self.assertEqual(events[0].reason, "pjl_eoj")

    def test_pjl_wrapped_legacy_languages_keep_exact_protocol(self) -> None:
        languages = {
            b"PCL3GUI": "pcl3gui",
            b"ESC/P": "escp",
            b"ESC/P2": "escp2",
            b"ESC/P-R": "escpr",
            b"ESC/PAGE": "escpage",
        }
        for language, expected in languages.items():
            with self.subTest(language=language):
                detector = PrintBoundaryDetector()
                stream = (
                    UEL
                    + b"@PJL JOB\r\n@PJL ENTER LANGUAGE="
                    + language
                    + b"\r\nprivate-page"
                    + UEL
                    + b"@PJL EOJ\r\n"
                    + UEL
                )

                events = detector.feed(stream, 1)

                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].protocol, expected)

    def test_hp_acl_firmware_is_identified_for_idle_completion(self) -> None:
        detector = PrintBoundaryDetector()
        detector.feed(b"JZJZ\x00agiACLDownload\x00HP LaserJet 1020", 100)

        event = detector.poll(200, 100)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.protocol, "hp_acl_firmware")

    def test_c_group_protocols_use_idle_timeout_and_keep_their_identity(self) -> None:
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
            "sharp_splc": b"SHARP CORPORATION\n@PJL ENTER LANGUAGE=SPLC\nprivate",
            "ricoh_rpcs": b"@PJL ENTER LANGUAGE=RPCS\nprivate",
            "ibm_afp": afp_record(b"one") + afp_record(b"two"),
            "zpl": b"^XA\n^FO20,20^A0N,30,30^FDReport^FS\n^XZ",
            "epl": b"N\r\nA50,50,0,4,1,1,N,Report\r\nP1\r\n",
            "cpcl": b"! 0 200 200 406 1\nPW 384\nT 0 0 30 40 Report\nPRINT\n",
            "printrex": b"PRINTREX raster stream",
        }
        for expected, content in samples.items():
            with self.subTest(expected=expected):
                detector = PrintBoundaryDetector()
                detector.feed(content, 100)
                event = detector.poll(200, 100)
                self.assertIsNotNone(event)
                assert event is not None
                self.assertEqual(event.protocol, expected)
                self.assertEqual(event.reason, "idle_timeout")

    def test_ambiguous_splc_stays_on_samsung_path(self) -> None:
        detector = PrintBoundaryDetector()
        detector.feed(b"@PJL ENTER LANGUAGE=SPLC\r\nprivate", 100)
        event = detector.poll(200, 100)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.protocol, "spl")


if __name__ == "__main__":
    unittest.main()
