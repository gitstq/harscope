"""解析器测试：容错性、脏数据兜底与错误出口。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from harscope.exceptions import HarParserError  # noqa: E402
from harscope.model import parse_date  # noqa: E402
from harscope.parser import load, loads, parse, sniff  # noqa: E402

from har_fixture import build_sample_har, sample_json  # noqa: E402


class TestSniff(unittest.TestCase):
    """顶层结构识别。"""

    def test_take_from_log(self) -> None:
        data = {"log": {"version": "1.2", "entries": []}}
        self.assertIs(sniff(data)["version"], "1.2")

    def test_flat_structure(self) -> None:
        data = {"entries": [], "creator": {"name": "x"}}
        self.assertIn("entries", sniff(data))

    def test_entries_array_only(self) -> None:
        self.assertEqual(sniff([]), {"entries": [], "version": "1.2"})

    def test_unknown_shape(self) -> None:
        self.assertEqual(sniff("nope"), {})


class TestLoads(unittest.TestCase):
    """文本/字节解析。"""

    def test_decode_bytes_with_bom(self) -> None:
        har = loads(sample_json().encode("utf-8"))
        self.assertEqual(har.entry_count, 14)

    def test_handle_bom_prefix(self) -> None:
        har = loads(b"\xef\xbb\xbf" + sample_json().encode("utf-8"))
        self.assertEqual(har.entry_count, 14)

    def test_invalid_json(self) -> None:
        with self.assertRaises(HarParserError):
            loads("{not json")

    def test_missing_entries(self) -> None:
        with self.assertRaises(HarParserError):
            loads(json.dumps({"log": {"version": "1.2"}}))

    def test_empty_entries(self) -> None:
        with self.assertRaises(HarParserError):
            loads(json.dumps({"log": {"version": "1.2", "entries": []}}))


class TestLoad(unittest.TestCase):
    """文件路径解析。"""

    def test_load_from_disk(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".har", delete=False,
                                         encoding="utf-8") as handle:
            handle.write(sample_json())
            path = handle.name
        try:
            har = load(path)
            self.assertEqual(har.entry_count, 14)
            self.assertIn(path, har.source)
        finally:
            os.unlink(path)

    def test_missing_file(self) -> None:
        with self.assertRaises(HarParserError):
            load("/definitely/not/here.har")


class TestDirtyData(unittest.TestCase):
    """各种脏字段的兜底行为。"""

    def setUp(self) -> None:
        self.har = loads(sample_json())

    def test_version_and_creator(self) -> None:
        self.assertEqual(self.har.version, "1.2")
        self.assertEqual(self.har.creator_name, "HarScope Fixture")
        self.assertEqual(self.har.browser_name, "Chrome")

    def test_page_parsed(self) -> None:
        self.assertEqual(len(self.har.pages), 1)
        self.assertEqual(self.har.pages[0].title, "示例商城 · 首页")
        self.assertEqual(self.har.pages[0].on_load_ms, 640.0)

    def test_negative_headers_size_becomes_none(self) -> None:
        entry = self.har.entries[5]
        self.assertIsNone(entry.response.headers_size)
        self.assertGreater(entry.response.headers_size_or_estimate, 0)

    def test_missing_content_node(self) -> None:
        entry = self.har.entries[5]
        self.assertEqual(entry.response.uncompressed_body_size, 5120)
        self.assertEqual(entry.response.mime_type, "")

    def test_missing_started_datetime_is_backfilled(self) -> None:
        entry = self.har.entries[-1]
        self.assertIsNotNone(entry.started_date_time)
        self.assertGreater(entry.started_ms, 0)

    def test_har_resource_fields(self) -> None:
        first = self.har.entries[0]
        self.assertEqual(first.request.method, "GET")
        self.assertEqual(first.response.status, 200)
        self.assertTrue(first.is_secure)
        self.assertEqual(first.host, "shop.example.com")

    def test_entries_for_page(self) -> None:
        self.assertEqual(len(self.har.entries_for_page("page_0")), 14)

    def test_warning_recorded_for_missing_sizes(self) -> None:
        joined = " ".join(self.har.warnings)
        self.assertIn("_transferSize", joined)


class TestParseDate(unittest.TestCase):
    """时间解析兼容多种写法。"""

    def test_z_suffix(self) -> None:
        self.assertIsNotNone(parse_date("2026-10-30T09:00:00.000Z"))

    def test_offset_without_colon(self) -> None:
        self.assertIsNotNone(parse_date("2026-10-30T09:00:00.000+0800"))

    def test_naive_datetime(self) -> None:
        moment = parse_date("2026-10-30T09:00:00")
        self.assertIsNotNone(moment)
        self.assertIsNotNone(moment.tzinfo)

    def test_invalid(self) -> None:
        self.assertIsNone(parse_date("not-a-date"))
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date(None))


if __name__ == "__main__":
    unittest.main()
