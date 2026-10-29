"""导出层与终端渲染层测试。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from harscope import analyze, loads  # noqa: E402
from harscope.exceptions import ExportError  # noqa: E402
from harscope.exporters import (  # noqa: E402
    to_csv,
    to_entry_rows,
    to_html_report,
    to_json,
    to_markdown,
    to_svg_waterfall,
    write_export,
)
from harscope.render import (  # noqa: E402
    bar,
    human_bytes,
    human_count,
    human_ms,
    pad,
    rule,
    table,
    truncate,
)
from harscope.security import audit  # noqa: E402

from har_fixture import sample_json  # noqa: E402


class ExporterTestCase(unittest.TestCase):
    """共享的分析对象。"""

    def setUp(self) -> None:
        self.har = loads(sample_json())
        self.analysis = analyze(self.har)
        self.security = audit(self.har)


class TestJsonExport(ExporterTestCase):
    """JSON 导出。"""

    def test_valid_json_with_summary(self) -> None:
        parsed = json.loads(to_json(self.analysis, audit=self.security))
        self.assertEqual(parsed["summary"]["requests"], 14)
        self.assertIn("domains", parsed)

    def test_entries_included_on_demand(self) -> None:
        parsed = json.loads(to_json(self.analysis, include_entries=True))
        self.assertEqual(len(parsed["entries"]), 14)
        self.assertNotIn("entries", json.loads(to_json(self.analysis)))

    def test_security_section_optional(self) -> None:
        self.assertNotIn("security", json.loads(to_json(self.analysis)))
        self.assertIn("security", json.loads(to_json(self.analysis, audit=self.security)))


class TestCsvExport(ExporterTestCase):
    """CSV 导出。"""

    def test_bom_and_rows(self) -> None:
        content = to_csv(self.analysis.entries)
        self.assertTrue(content.startswith("﻿"))
        lines = content.strip().splitlines()
        self.assertEqual(len(lines), 15)
        self.assertEqual(lines[0].count(","), 13)

    def test_entry_rows_shape(self) -> None:
        rows = to_entry_rows(self.analysis.entries)
        self.assertEqual(len(rows), 15)
        self.assertEqual(len(rows[0]), len(rows[1]))


class TestMarkdownExport(ExporterTestCase):
    """Markdown 导出。"""

    def test_contains_key_sections(self) -> None:
        content = to_markdown(self.analysis, audit=self.security)
        for needle in ("# HarScope", "## 总览", "## 状态码分布", "## 域名分布", "## 安全审计"):
            self.assertIn(needle, content)

    def test_escapes_pipes_in_title(self) -> None:
        content = to_markdown(self.analysis)
        self.assertIn("|", content)
        self.assertTrue(content.startswith("# "))


class TestSvgExport(ExporterTestCase):
    """SVG 瀑布图。"""

    def test_svg_structure(self) -> None:
        svg = to_svg_waterfall(self.analysis)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.rstrip().endswith("</svg>"))
        self.assertIn("xmlns", svg)

    def test_empty_fallback(self) -> None:
        empty = analyze(loads(sample_json()))
        empty.entries = tuple()
        svg = to_svg_waterfall(empty)
        self.assertIn("svg", svg)


class TestHtmlReport(ExporterTestCase):
    """HTML 报告。"""

    def test_self_contained(self) -> None:
        html = to_html_report(self.analysis, audit=self.security)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("<style>", html)
        self.assertIn("<svg", html)
        self.assertNotIn("http://cdn", html)

    def test_escapes_user_content(self) -> None:
        html = to_html_report(self.analysis)
        self.assertIn("HarScope", html)


class TestWriteExport(unittest.TestCase):
    """写盘行为。"""

    def test_write_and_refuse_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "out.txt")
            write_export("hello", path)
            self.assertTrue(os.path.exists(path))
            with self.assertRaises(ExportError):
                write_export("hi", path)
            write_export("hi", path, force=True)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "hi")


class TestRenderHelpers(unittest.TestCase):
    """渲染层纯函数。"""

    def test_human_bytes(self) -> None:
        self.assertEqual(human_bytes(0), "0 B")
        self.assertEqual(human_bytes(1024), "1.0 KB")
        self.assertEqual(human_bytes(1024 * 1024), "1.0 MB")
        self.assertEqual(human_bytes(-2048), "-2.0 KB")
        self.assertEqual(human_bytes(None), "0 B")

    def test_human_ms(self) -> None:
        self.assertEqual(human_ms(0), "0.0 ms")
        self.assertIn("ms", human_ms(999))
        self.assertIn("s", human_ms(9999))
        self.assertEqual(human_ms(-5), "-5.0 ms")

    def test_human_count(self) -> None:
        self.assertEqual(human_count(12), "12")
        self.assertEqual(human_count(1234567), "1,234,567")

    def test_bar_clamped(self) -> None:
        self.assertEqual(bar(-1), "░" * 20)
        self.assertEqual(bar(2), "█" * 20)
        self.assertEqual(len(bar(0.25, 8)), 8)

    def test_truncate_width_aware(self) -> None:
        self.assertEqual(truncate("hello", 10), "hello")
        self.assertTrue(truncate("hello world", 5).endswith("…"))
        self.assertLessEqual(len(truncate("中文字符串比较长", 8)), 10)

    def test_pad_width_aware(self) -> None:
        self.assertEqual(pad("中文", 8), "中文    ")
        self.assertEqual(pad("ab", 4, align="right"), "  ab")

    def test_table_renders(self) -> None:
        rendered = table(["A", "B"], [["1", "2"], ["3", "4"]],
                         aligns=["left", "right"])
        lines = rendered.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(line.strip() for line in lines))

    def test_table_empty(self) -> None:
        self.assertEqual(table([], []), "")

    def test_rule(self) -> None:
        self.assertTrue(rule("标题").startswith("─"))
        self.assertTrue(rule().strip())


if __name__ == "__main__":
    unittest.main()
