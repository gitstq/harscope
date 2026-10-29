"""录制器测试。

网络相关的用例默认跳过，设置 ``HARSCOPE_TEST_NETWORK=1`` 才会真正联网，
保证 CI 与离线环境下测试依然稳定。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from harscope.parser import loads  # noqa: E402
from harscope.recorder import (  # noqa: E402
    DEFAULT_TIMEOUT,
    RecordOptions,
    _AssetCollector,
    _collect_assets,
    _decode_body,
    _extract_title,
    _fetch_assets_parallel,
    har_template,
)

RUN_NETWORK = os.environ.get("HARSCOPE_TEST_NETWORK") == "1"

SAMPLE_HTML = (
    b'<!DOCTYPE html>\n<html lang="zh-CN"><head>\n<meta charset="utf-8">\n'
    b"<title>\xe7\xa4\xba\xe4\xbe\x8b\xe7\xab\x99\xe7\x82\xb9 &amp; Demo</title>\n"
    b'<link rel="stylesheet" href="/static/main.css">\n'
    b'<link rel="preload" as="script" href="/static/boot.js">\n'
    b'<link rel="icon" href="/favicon.ico">\n'
    b'<script src="https://example.com/static/app.js"></script>\n'
    b"</head><body>\n"
    b'<img src="/static/logo.png" '
    b'srcset="/static/logo@1x.png 1x, /static/logo@2x.png 2x">\n'
    b'<img src="data:image/gif;base64,AAAA">\n'
    b"</body></html>"
)


class TestHtmlParsing(unittest.TestCase):
    """本地 HTML 解析，不需要网络。"""

    def test_assets_collected(self) -> None:
        parser = _AssetCollector("https://example.com/index.html")
        parser.feed(SAMPLE_HTML.decode("utf-8"))
        parser.close()
        joined = " ".join(parser.assets)
        self.assertIn("/static/main.css", joined)
        self.assertIn("/static/boot.js", joined)
        self.assertIn("/static/logo@1x.png", joined)
        self.assertNotIn("favicon", joined)
        self.assertFalse(any("data:" in url for url in parser.assets))

    def test_collect_assets_resolves_absolute(self) -> None:
        options = RecordOptions(max_assets=10)
        assets = _collect_assets(SAMPLE_HTML, "https://example.com/index.html", options)
        self.assertTrue(assets)
        self.assertTrue(all(url.startswith("https://example.com/") for url in assets))

    def test_extract_title(self) -> None:
        self.assertIn("示例", _extract_title(SAMPLE_HTML))

    def test_extract_title_missing(self) -> None:
        self.assertEqual(_extract_title(b"<html><body>hi</body></html>"), "")

    def test_decode_body_gzip(self) -> None:
        import gzip

        payload = gzip.compress(b"hello world" * 100)
        plain, size = _decode_body(payload, "gzip")
        self.assertEqual(size, len(plain))
        self.assertTrue(plain.startswith(b"hello"))

    def test_decode_body_unknown_encoding(self) -> None:
        plain, size = _decode_body(b"abc", "identity")
        self.assertEqual((plain, size), (b"abc", 3))

    def test_decode_body_empty(self) -> None:
        self.assertEqual(_decode_body(b"", "gzip"), (b"", 0))


class TestHarTemplate(unittest.TestCase):
    """HAR 骨架。"""

    def test_template_shape(self) -> None:
        template = har_template()
        self.assertEqual(template["log"]["version"], "1.2")
        self.assertEqual(template["log"]["creator"]["name"], "harscope")
        self.assertEqual(template["log"]["entries"], [])

    def test_template_serialisable(self) -> None:
        json.dumps(har_template(), ensure_ascii=False)


class TestRecordOptions(unittest.TestCase):
    """配置对象。"""

    def test_defaults(self) -> None:
        options = RecordOptions()
        self.assertEqual(options.timeout, DEFAULT_TIMEOUT)
        headers = options.request_headers()
        self.assertIn("User-Agent", headers)
        self.assertTrue(headers["User-Agent"].startswith("HarScope/"))

    def test_custom_headers_override(self) -> None:
        options = RecordOptions(headers={"X-Trace": "abc"})
        self.assertEqual(options.request_headers()["X-Trace"], "abc")


class TestRecordedHarConsumed(unittest.TestCase):
    """把一份「模拟录制结果」喂给解析器，验证端到端兼容。"""

    def _fake_record(self) -> dict:
        entries = []
        base = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)
        for index in range(3):
            moment = base.replace(microsecond=0)
            moment = moment.replace(second=index)
            entries.append({
                "startedDateTime": moment.isoformat(),
                "time": 120.5,
                "request": {
                    "method": "GET",
                    "url": "https://example.com/a%d.js" % index,
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": "user-agent", "value": "x"}],
                    "queryString": [],
                    "headersSize": -1,
                    "bodySize": 0,
                },
                "response": {
                    "status": 200,
                    "statusText": "OK",
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": "content-type", "value": "application/javascript"}],
                    "content": {"size": 4096, "mimeType": "application/javascript"},
                    "headersSize": -1,
                    "bodySize": 1024,
                    "_transferSize": 1024,
                    "redirectURL": "",
                },
                "cache": {},
                "timings": {"blocked": 0, "dns": 2.1, "connect": 5.0, "ssl": 12.0,
                            "send": 0.4, "wait": 80.0, "receive": 21.0},
                "serverIPAddress": "1.2.3.4",
                "pageref": "page_0",
            })
        template = har_template()
        template["log"]["entries"] = entries
        template["log"]["pages"] = [{
            "startedDateTime": base.isoformat(),
            "id": "page_0",
            "title": "demo",
            "pageTimings": {"onLoad": 640.0},
        }]
        return template

    def test_recorded_har_is_analysable(self) -> None:
        har = loads(json.dumps(self._fake_record(), ensure_ascii=False))
        self.assertEqual(har.entry_count, 3)
        self.assertEqual(har.pages[0].title, "demo")
        first = har.entries[0]
        self.assertEqual(first.response.mime_type, "application/javascript")
        self.assertAlmostEqual(first.timings.wait, 80.0)
        self.assertIsNone(first.response.headers_size)
        self.assertGreater(first.response.headers_size_or_estimate, 0)


@unittest.skipUnless(RUN_NETWORK, "需要网络：设置 HARSCOPE_TEST_NETWORK=1 启用")
class TestNetworkRecording(unittest.TestCase):
    """真实网络录制（默认跳过）。"""

    def test_record_example_com(self) -> None:
        har = record_url("https://example.com", RecordOptions(max_assets=2, timeout=10))
        entries = har["log"]["entries"]
        self.assertTrue(entries)
        self.assertEqual(entries[0]["request"]["url"], "https://example.com")
        self.assertIn("timings", entries[0])

    def test_record_output_is_valid_har(self) -> None:
        har = record_url("https://example.com", RecordOptions(max_assets=1, timeout=10))
        values = loads(json.dumps(har, ensure_ascii=False))
        self.assertGreater(values.entry_count, 0)


def record_url(url: str, options: RecordOptions) -> dict:
    """延迟导入 ``record``，避免测试文件顶层依赖网络模块。"""
    from harscope.recorder import record

    return record(url, options)


class TestParallelAssetFetching(unittest.TestCase):
    """并发抓取的兜底行为。"""

    def test_empty_assets_noop(self) -> None:
        sink: list = []
        _fetch_assets_parallel(sink, [], RecordOptions())
        self.assertEqual(sink, [])

    def test_failing_assets_are_ignored(self) -> None:
        sink: list = []
        _fetch_assets_parallel(
            sink, ["https://127.0.0.1:9/nope.js"], RecordOptions(timeout=0.5)
        )
        self.assertEqual(sink, [])


if __name__ == "__main__":
    unittest.main()
