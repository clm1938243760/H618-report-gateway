from __future__ import annotations

import unittest

from gadget_msc_printer.print_boundary import PrintBoundaryDetector, UEL


PCL_START = UEL + b"\x1bE\x1b*t300R\x1b*r1A"
PCL_END = b"\x1b*rC\x0c\x1bE" + UEL


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

    def test_unknown_stream_uses_idle_timeout(self) -> None:
        detector = PrintBoundaryDetector()
        detector.feed(b"\x00vendor-private-data", 100)
        self.assertIsNone(detector.poll(199, 100))
        event = detector.poll(200, 100)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.reason, "idle_timeout")
        self.assertEqual(event.protocol, "unknown")


if __name__ == "__main__":
    unittest.main()
