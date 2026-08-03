from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from gadget_msc_printer.config import PrinterConfig
from gadget_msc_printer.print_capture import PrintCapture


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


if __name__ == "__main__":
    unittest.main()
