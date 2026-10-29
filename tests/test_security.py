"""安全审计层测试。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from harscope import loads  # noqa: E402
from harscope.model import HarEntry  # noqa: E402
from harscope.security import SENSITIVE_QUERY_KEYS, SecurityAudit, audit  # noqa: E402

from har_fixture import sample_json  # noqa: E402


class TestAuditOnSample(unittest.TestCase):
    """针对样本 HAR 的审计结果。"""

    def setUp(self) -> None:
        self.result = audit(loads(sample_json()))

    def test_https_ratio(self) -> None:
        self.assertAlmostEqual(self.result.https_ratio, 13 / 14, places=3)

    def test_high_findings_present(self) -> None:
        categories = {f.category for f in self.result.findings if f.severity == "high"}
        self.assertIn("混合内容", categories)

    def test_missing_headers_counted(self) -> None:
        self.assertGreater(self.result.missing_header_counts.get("referrer-policy", 0), 0)

    def test_score_and_grade(self) -> None:
        self.assertGreaterEqual(self.result.score, 0)
        self.assertLessEqual(self.result.score, 100)
        self.assertIn(self.result.grade, "ABCDE")

    def test_dict_serialisable(self) -> None:
        import json

        payload = json.dumps(self.result.to_dict(), ensure_ascii=False)
        self.assertIn("findings", payload)

    def test_by_severity(self) -> None:
        total = sum(
            len(self.result.by_severity(level))
            for level in ("high", "medium", "low", "info")
        )
        self.assertEqual(total, len(self.result.findings))


class TestAuditEdgeCases(unittest.TestCase):
    """极端输入。"""

    def test_empty_har_scores_well(self) -> None:
        har = loads(sample_json())
        har.entries = []
        result = audit(har)
        self.assertEqual(result.https_ratio, 1.0)
        self.assertEqual(result.findings, [])

    def test_all_https_and_headers_scores_near_full(self) -> None:
        har = loads(sample_json())
        good_headers = [
            {"name": "strict-transport-security", "value": "max-age=31536000"},
            {"name": "content-security-policy", "value": "default-src 'self'"},
            {"name": "x-content-type-options", "value": "nosniff"},
            {"name": "x-frame-options", "value": "DENY"},
            {"name": "referrer-policy", "value": "strict-origin"},
            {"name": "permissions-policy", "value": "geolocation=()"},
            {"name": "cross-origin-opener-policy", "value": "same-origin"},
            {"name": "cache-control", "value": "max-age=600"},
        ]
        for entry in har.entries:
            entry.request.url = entry.request.url.replace("http://", "https://")
            entry.response.mime_type = "text/html"
            entry.response.headers = [
                type(entry.response.headers[0])(name=h["name"], value=h["value"])
                for h in good_headers
            ]
            entry.response.cookies = []
            entry.request.query_string = []
        result = audit(har)
        self.assertGreaterEqual(result.score, 70)
        self.assertNotIn("E", result.grade)

    def test_sensitive_query_detected(self) -> None:
        har = loads(sample_json())
        entry: HarEntry = har.entries[0]
        entry.request.query_string = [("access_token", "abc")]
        result = audit(har)
        categories = {f.category for f in result.findings}
        self.assertIn("凭据泄漏", categories)
        self.assertIn("access_token", SENSITIVE_QUERY_KEYS)

    def test_cookie_flags(self) -> None:
        from harscope.model import HarCookie

        har = loads(sample_json())
        for entry in har.entries:
            entry.response.cookies = [
                HarCookie(name="session", value="x", secure=False, http_only=False)
            ]
        result = audit(har)
        categories = {f.category for f in result.findings}
        self.assertIn("Cookie 属性", categories)
        messages = " ".join(
            f.message for f in result.findings if f.category == "Cookie 属性"
        )
        self.assertIn("HttpOnly", messages)


class TestScoring(unittest.TestCase):
    """评分公式的单调性。"""

    def test_more_high_findings_lowers_score(self) -> None:
        base = SecurityAudit(https_requests=10, http_requests=0, documents_checked=1)
        worse = SecurityAudit(https_requests=10, http_requests=0, documents_checked=1)
        from harscope.security import Finding

        for _ in range(3):
            worse.findings.append(Finding("high", "x", "y"))
        self.assertLess(worse.score, base.score)

    def test_lower_https_ratio_lowers_score(self) -> None:
        good = SecurityAudit(https_requests=100, http_requests=0)
        bad = SecurityAudit(https_requests=50, http_requests=50)
        self.assertLess(bad.score, good.score)


if __name__ == "__main__":
    unittest.main()
