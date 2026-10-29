"""分析层测试：聚合指标的正确性与边界情况。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from harscope import analyze, loads  # noqa: E402
from harscope.analyze import percentile  # noqa: E402

from har_fixture import build_sample_har  # noqa: E402


class AnalysisTestCase(unittest.TestCase):
    """共享的一份样本分析。"""

    def setUp(self) -> None:
        self.har = loads(build_sample_har_json())
        self.analysis = analyze(self.har)


def build_sample_har_json() -> str:
    """返回样本 HAR 的 JSON 文本。"""
    from har_fixture import sample_json

    return sample_json()


class TestScale(AnalysisTestCase):
    """规模类指标。"""

    def test_request_count(self) -> None:
        self.assertEqual(self.analysis.total_requests, 14)

    def test_unique_hosts(self) -> None:
        self.assertEqual(self.analysis.unique_hosts, 5)
        self.assertIn("cdn.example.com", self.analysis.hosts)

    def test_https_ratio(self) -> None:
        self.assertAlmostEqual(self.analysis.https_ratio, 13 / 14, places=3)
        self.assertEqual(self.analysis.insecure_requests, 1)

    def test_duration_positive(self) -> None:
        self.assertGreater(self.analysis.duration_ms, 0)
        self.assertGreater(self.analysis.total_time_ms, self.analysis.duration_ms / 2)


class TestSizes(AnalysisTestCase):
    """体积类指标。"""

    def test_transfer_breakdown(self) -> None:
        self.assertEqual(
            self.analysis.body_transfer_bytes + self.analysis.header_bytes,
            self.analysis.transfer_bytes,
        )

    def test_compression_saving(self) -> None:
        self.assertGreater(self.analysis.compression_saving_bytes, 0)
        self.assertGreater(self.analysis.compression_saving_ratio, 0.2)

    def test_uncompressed_is_bigger(self) -> None:
        self.assertGreaterEqual(
            self.analysis.uncompressed_body_bytes, self.analysis.body_transfer_bytes
        )

    def test_header_ratio_bounded(self) -> None:
        self.assertGreaterEqual(self.analysis.header_ratio, 0)
        self.assertLessEqual(self.analysis.header_ratio, 1)


class TestTiming(AnalysisTestCase):
    """时间类指标。"""

    def test_percentile_boundaries(self) -> None:
        self.assertEqual(percentile([], 0.95), 0.0)
        self.assertEqual(percentile([42.0], 0.95), 42.0)
        self.assertEqual(percentile([1.0, 2.0], 0.0), 1.0)
        self.assertEqual(percentile([1.0, 2.0], 1.0), 2.0)
        self.assertAlmostEqual(percentile([1.0, 2.0, 3.0, 4.0], 0.5), 2.5, places=5)

    def test_p50_le_p95(self) -> None:
        self.assertLessEqual(self.analysis.p50_ms, self.analysis.p95_ms)

    def test_average_between_extremes(self) -> None:
        values = [e.time_ms for e in self.analysis.entries]
        self.assertGreaterEqual(self.analysis.average_ms, min(values) - 1e-6)
        self.assertLessEqual(self.analysis.average_ms, max(values) + 1e-6)

    def test_parallelism_reasonable(self) -> None:
        self.assertGreater(self.analysis.parallelism, 0)


class TestStatus(AnalysisTestCase):
    """状态码聚合。"""

    def test_classes_sum(self) -> None:
        self.assertEqual(sum(self.analysis.status_classes.values()), 14)

    def test_error_entries(self) -> None:
        self.assertEqual(len(self.analysis.error_entries), 1)
        self.assertEqual(self.analysis.error_entries[0].response.status, 500)

    def test_client_errors(self) -> None:
        self.assertEqual(len(self.analysis.client_error_entries), 1)

    def test_success_ratio_in_range(self) -> None:
        self.assertGreater(self.analysis.success_ratio, 0.5)
        self.assertLessEqual(self.analysis.success_ratio, 1.0)


class TestGrouping(AnalysisTestCase):
    """分组与排序。"""

    def test_domain_stats_ordering(self) -> None:
        stats = self.analysis.domain_stats(3)
        self.assertEqual(len(stats), 3)
        self.assertGreaterEqual(stats[0].transfer_bytes, stats[-1].transfer_bytes)
        self.assertTrue(0 <= stats[0].transfer_ratio <= 1)

    def test_mime_stats_has_entries(self) -> None:
        stats = self.analysis.mime_stats(20)
        self.assertTrue(stats)
        mime_names = [s.mime_type for s in stats]
        self.assertIn("application/javascript", mime_names)

    def test_duplicates_found(self) -> None:
        groups = self.analysis.duplicates()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].count, 2)
        self.assertGreater(groups[0].wasted_bytes, 0)

    def test_cache_hit_detected(self) -> None:
        self.assertEqual(self.analysis.cache_hits, 1)

    def test_redirects(self) -> None:
        self.assertEqual(len(self.analysis.redirect_chains()), 1)

    def test_slowest_and_largest(self) -> None:
        slowest = self.analysis.slowest(2)
        self.assertEqual(len(slowest), 2)
        self.assertGreaterEqual(slowest[0].time_ms, slowest[1].time_ms)
        largest = self.analysis.largest(2)
        self.assertGreaterEqual(largest[0].total_size, largest[1].total_size)


class TestWaterfall(AnalysisTestCase):
    """瀑布图数据。"""

    def test_rows_match_requests(self) -> None:
        rows = self.analysis.waterfall(limit=100)
        self.assertEqual(len(rows), 14)

    def test_offsets_sorted(self) -> None:
        rows = self.analysis.waterfall(limit=100)
        offsets = [row.offset_ms for row in rows]
        self.assertEqual(offsets, sorted(offsets))

    def test_phase_sum_equals_duration(self) -> None:
        for row in self.analysis.waterfall(limit=100):
            total = sum(value for _phase, value in row.phases)
            self.assertAlmostEqual(total, row.duration_ms, places=1)

    def test_limit_truncates_to_slowest(self) -> None:
        rows = self.analysis.waterfall(limit=3)
        self.assertEqual(len(rows), 3)
        slowest_times = sorted(e.time_ms for e in self.analysis.entries)[-3:]
        self.assertIn(min(slowest_times), [round(r.duration_ms, 4) for r in rows] + [0])


class TestPages(AnalysisTestCase):
    """页面聚合。"""

    def test_page_stats(self) -> None:
        stats = self.analysis.page_stats()
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0].requests, 14)
        self.assertEqual(stats[0].on_load_ms, 640.0)

    def test_summary_dict_serialisable(self) -> None:
        import json

        payload = json.dumps(self.analysis.summary_dict(), ensure_ascii=False)
        self.assertIn("requests", payload)


if __name__ == "__main__":
    unittest.main()
