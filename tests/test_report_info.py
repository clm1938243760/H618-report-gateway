from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from gadget_msc_printer.config import DeviceConfig
from gadget_msc_printer.report_info import ReportInfoManager


class ReportInfoTests(unittest.TestCase):
    def test_writes_exact_minimal_xml_without_namespaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ReportInfo.xml"
            manager = ReportInfoManager(DeviceConfig(report_info_path=str(path)))
            snapshot = manager.write("DEV<&1", "陈医生", "DOC-2")
            text = path.read_text(encoding="utf-8")
            root = ET.fromstring(path.read_bytes())
        self.assertTrue(text.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertNotIn("xmlns", text)
        self.assertEqual(root.tag, "UploadReportInfo")
        self.assertEqual([child.tag for child in root], ["DeviceCode", "ExamDoct", "ExamDoctCode"])
        self.assertEqual(root.findtext("DeviceCode"), "DEV<&1")
        self.assertEqual(root.findtext("ExamDoct"), "陈医生")
        self.assertEqual(snapshot.device_code, "DEV<&1")
        self.assertEqual(snapshot.exam_doct, "陈医生")

    def test_rejects_extra_xml_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ReportInfo.xml"
            path.write_text(
                "<UploadReportInfo><DeviceCode>D</DeviceCode><ExamDoct>Doctor</ExamDoct><ExamDoctCode>E</ExamDoctCode><IP>X</IP></UploadReportInfo>",
                encoding="utf-8",
            )
            manager = ReportInfoManager(DeviceConfig(report_info_path=str(path)))
            with self.assertRaisesRegex(ValueError, "DeviceCode, ExamDoct"):
                manager.snapshot()

    def test_rejects_namespace_attributes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ReportInfo.xml"
            path.write_text(
                '<UploadReportInfo xmlns:xsi="urn:test"><DeviceCode>D</DeviceCode><ExamDoct>Doctor</ExamDoct><ExamDoctCode>E</ExamDoctCode></UploadReportInfo>',
                encoding="utf-8",
            )
            manager = ReportInfoManager(DeviceConfig(report_info_path=str(path)))
            with self.assertRaisesRegex(ValueError, "namespace"):
                manager.snapshot()


if __name__ == "__main__":
    unittest.main()
