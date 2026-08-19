from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from gadget_msc_printer.config import PrinterConfig
from gadget_msc_printer.print_boundary import BoundaryEvent
from gadget_msc_printer.print_capture import PrintCapture


UEL = b"\x1b%-12345X"
PCL_JOB = UEL + b"\x1bE\x1b*t300Rpage\x1b*rC\x0c\x1bE" + UEL


class FakePoll:
    def __init__(self, responses: list[list[tuple[int, int]]]) -> None:
        self.responses = responses

    def register(self, fd: int, events: int) -> None:
        del fd, events

    def poll(self, timeout: int) -> list[tuple[int, int]]:
        del timeout
        return self.responses.pop(0) if self.responses else []


class BlockingConverter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.started = threading.Event()
        self.release = threading.Event()
        self.converted: list[Path] = []

    def convert(self, source: str | Path, source_type: str) -> Path:
        path = Path(source)
        self.started.set()
        self.release.wait(5)
        target = self.output_dir / f"{path.stem}.pdf"
        target.write_bytes(b"%PDF-1.4\n%%EOF\n")
        self.converted.append(path)
        return target


class IgnoringConverter:
    def ignore_reason(self, source: str | Path) -> str:
        del source
        return "HP ACL firmware/initialization stream"

    def convert(self, source: str | Path, source_type: str) -> Path:
        del source, source_type
        raise AssertionError("ignored streams must not be converted")


class PrintCaptureTests(unittest.TestCase):
    def test_waiting_warning_is_rate_limited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = PrintCapture(PrinterConfig(output_dir=directory))
            with (
                patch(
                    "gadget_msc_printer.print_capture.time.monotonic",
                    side_effect=[1.0, 20.0, 62.0],
                ),
                patch("gadget_msc_printer.print_capture.LOGGER.warning") as warning,
            ):
                capture._log_waiting("waiting")
                capture._log_waiting("waiting")
                capture._log_waiting("waiting")

        self.assertEqual(warning.call_count, 2)

    def test_completed_job_is_atomically_published_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = PrintCapture(
                PrinterConfig(output_dir=directory, min_job_bytes=1),
                converter=None,
            )
            final_path = root / "print_test.prn"
            with patch.object(capture, "_new_job_path", return_value=final_path):
                active = capture._write_chunk(
                    None,
                    b"complete-pcl-job",
                    1_000_000_000,
                    datetime(2026, 8, 14, tzinfo=timezone.utc),
                )
                capture._complete_job(
                    active,
                    BoundaryEvent(0, "pcl", "pcl_uel"),
                    1_100_000_000,
                    datetime(2026, 8, 14, 0, 0, 1, tzinfo=timezone.utc),
                )

            metadata = capture._read_metadata(final_path)
            self.assertEqual(final_path.read_bytes(), b"complete-pcl-job")
            self.assertFalse((root / "print_test.prn.part").exists())
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata["protocol"], "pcl")
            self.assertEqual(metadata["completion_reason"], "pcl_uel")
            self.assertEqual(metadata["received_bytes"], len(b"complete-pcl-job"))
            self.assertEqual(metadata["conversion_status"], "disabled")

    def test_blocked_converter_does_not_block_next_job_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter = BlockingConverter(root)
            capture = PrintCapture(
                PrinterConfig(output_dir=directory, min_job_bytes=1),
                converter=converter,  # type: ignore[arg-type]
            )
            names = iter((root / "first.prn", root / "second.prn"))
            with patch.object(capture, "_new_job_path", side_effect=lambda: next(names)):
                capture._start_converter_worker()
                first = capture._write_chunk(None, b"first", 1, datetime.now(timezone.utc))
                capture._complete_job(
                    first,
                    BoundaryEvent(0, "pcl", "pcl_uel"),
                    2,
                    datetime.now(timezone.utc),
                )
                self.assertTrue(converter.started.wait(1))

                second = capture._write_chunk(None, b"second", 3, datetime.now(timezone.utc))
                capture._complete_job(
                    second,
                    BoundaryEvent(0, "pcl", "pcl_uel"),
                    4,
                    datetime.now(timezone.utc),
                )
                self.assertTrue((root / "second.prn").is_file())
                self.assertEqual(converter.converted, [])

                converter.release.set()
                capture._conversion_queue.join()
                capture._conversion_queue.put(None)
                assert capture._converter_thread is not None
                capture._converter_thread.join(1)

            self.assertEqual(
                [path.name for path in converter.converted],
                ["first.prn", "second.prn"],
            )

    def test_partial_job_is_recovered_but_legacy_prn_is_not_reprocessed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter = BlockingConverter(root)
            converter.release.set()
            capture = PrintCapture(
                PrinterConfig(output_dir=directory, min_job_bytes=1),
                converter=converter,  # type: ignore[arg-type]
            )
            (root / "recovered.prn.part").write_bytes(b"partial-data")
            (root / "legacy.prn").write_bytes(b"old-complete-data")
            capture._recover_pending_jobs()
            capture._start_converter_worker()
            capture._conversion_queue.join()
            capture._conversion_queue.put(None)
            assert capture._converter_thread is not None
            capture._converter_thread.join(1)

            self.assertTrue((root / "recovered.prn").is_file())
            metadata = capture._read_metadata(root / "recovered.prn")
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata["completion_reason"], "recovered_after_restart")
            self.assertEqual([path.name for path in converter.converted], ["recovered.prn"])

    def test_device_disconnect_completion_reason_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = PrintCapture(
                PrinterConfig(output_dir=directory, min_job_bytes=1),
                converter=None,
            )
            final_path = root / "disconnect.prn"
            with patch.object(capture, "_new_job_path", return_value=final_path):
                active = capture._write_chunk(None, b"data", 1, datetime.now(timezone.utc))
                capture._complete_job(
                    active,
                    BoundaryEvent(0, "unknown", "device_disconnect"),
                    2,
                    datetime.now(timezone.utc),
                )
            metadata = capture._read_metadata(final_path)
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata["completion_reason"], "device_disconnect")

    def test_firmware_stream_is_marked_ignored_without_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "firmware.prn"
            source.write_bytes(b"firmware")
            capture = PrintCapture(
                PrinterConfig(output_dir=directory, min_job_bytes=1),
                converter=IgnoringConverter(),  # type: ignore[arg-type]
            )
            capture._write_metadata(source, {"conversion_status": "pending"})

            capture._convert_job(source)

            metadata = capture._read_metadata(source)
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata["conversion_status"], "ignored")
            self.assertIn("firmware", metadata["conversion_skip_reason"].lower())

    def test_capture_once_splits_back_to_back_jobs_from_one_usb_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = PrintCapture(
                PrinterConfig(output_dir=directory, min_job_bytes=1),
                converter=None,
            )
            paths = iter((root / "first.prn", root / "second.prn"))

            def read_once(fd: int, size: int) -> bytes:
                del fd, size
                capture.stop()
                return PCL_JOB + PCL_JOB

            with (
                patch.object(capture, "_new_job_path", side_effect=lambda: next(paths)),
                patch("gadget_msc_printer.print_capture.os.O_NONBLOCK", 0x800, create=True),
                patch("gadget_msc_printer.print_capture.os.open", return_value=99),
                patch("gadget_msc_printer.print_capture.os.read", side_effect=read_once),
                patch("gadget_msc_printer.print_capture.os.close"),
                patch("gadget_msc_printer.print_capture.select.POLLIN", 1, create=True),
                patch("gadget_msc_printer.print_capture.select.POLLERR", 8, create=True),
                patch("gadget_msc_printer.print_capture.select.POLLHUP", 16, create=True),
                patch("gadget_msc_printer.print_capture.select.POLLNVAL", 32, create=True),
                patch(
                    "gadget_msc_printer.print_capture.select.poll",
                    return_value=FakePoll([[(99, 1)]]),
                    create=True,
                ),
            ):
                capture._capture_once()

            self.assertEqual((root / "first.prn").read_bytes(), PCL_JOB)
            self.assertEqual((root / "second.prn").read_bytes(), PCL_JOB)


if __name__ == "__main__":
    unittest.main()
