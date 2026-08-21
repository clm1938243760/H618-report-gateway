from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from gadget_msc_printer.print_boundary import UEL
from scripts.replay_print_boundaries import discover_prn, replay_file


PCL_START = UEL + b"\x1bE\x1b*t300R\x1b*r1A"
PCL_END = b"\x1b*rC\x0c\x1bE" + UEL


class ReplayPrintBoundariesTests(unittest.TestCase):
    def test_replay_reports_absolute_offsets_for_back_to_back_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "two-jobs.prn"
            job = PCL_START + b"page" + PCL_END
            path.write_bytes(job + job)

            result = replay_file(path, chunk_size=len(job) + 3)

        self.assertEqual(result["boundary_count"], 2)
        self.assertEqual(
            [item["end_offset"] for item in result["boundaries"]],
            [len(job), len(job) * 2],
        )
        self.assertEqual(
            [item["reason"] for item in result["boundaries"]],
            ["pcl_uel", "pcl_uel"],
        )

    def test_unknown_stream_is_completed_by_idle_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.prn"
            path.write_bytes(b"\x00private-binary-data")

            result = replay_file(path, chunk_size=3, idle_timeout_ms=250)

        self.assertEqual(result["boundary_count"], 1)
        self.assertEqual(result["boundaries"][0]["end_offset"], result["size"])
        self.assertEqual(result["boundaries"][0]["reason"], "idle_timeout")

    def test_discovery_returns_latest_prn_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = root / "older.prn"
            latest = root / "latest.prn"
            ignored = root / "ignored.txt"
            older.write_bytes(b"old")
            latest.write_bytes(b"new")
            ignored.write_bytes(b"ignore")
            older.touch()
            latest.touch()
            older_mtime = older.stat().st_mtime - 10
            os.utime(older, (older_mtime, older_mtime))

            files = discover_prn([root], limit=1)

        self.assertEqual([path.name for path in files], ["latest.prn"])


if __name__ == "__main__":
    unittest.main()
