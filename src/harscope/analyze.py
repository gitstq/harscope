"""性能指标聚合分析。

这一层的职责是把一堆脏 HAR 记录变成**可以直接写进报告的数字**。
所有指标都做了「数据不足」的兜底：缺失值时按 0 处理，并在
:attr:`HarAnalysis.notes` 里留痕，绝不伪造精度。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .model import Har, HarEntry

__all__ = [
    "HarAnalysis",
    "DomainStat",
    "MimeStat",
    "DuplicateGroup",
    "WaterfallRow",
    "PageStat",
    "analyze",
    "percentile",
]

#: 默认 TOP-N 输出条数。
DEFAULT_TOP = 10


def percentile(values: Sequence[float], fraction: float) -> float:
    """线性插值分位数。

    :param values: 待统计的数值序列（无需预排序，内部会排序）。
    :param fraction: 0~1 之间的分位比例，如 ``0.95`` 表示 P95。
    :returns: 分位值；空序列返回 ``0.0``。
    """
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(max(fraction, 0.0), 1.0)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _sum(values: Iterable[float]) -> float:
    """累加浮点/整数序列，避免 ``sum`` 对浮点精度的意外爆炸。"""
    total = 0.0
    for value in values:
        total += float(value)
    return total


def _ratio(part: float, whole: float) -> float:
    """安全除法，分母为 0 时返回 ``0.0``。"""
    return (part / whole) if whole else 0.0


@dataclass
class DomainStat:
    """按域名聚合的统计项。"""

    host: str
    requests: int = 0
    transfer_bytes: int = 0
    body_bytes: int = 0
    header_bytes: int = 0
    total_ms: float = 0.0
    wait_ms: float = 0.0
    errors: int = 0
    secure: bool = True

    @property
    def avg_ms(self) -> float:
        """平均单请求耗时。"""
        return _ratio(self.total_ms, self.requests)

    @property
    def transfer_ratio(self) -> float:
        """占位比例（0~1），由 :meth:`HarAnalysis.domain_stats` 回填。"""
        return getattr(self, "_transfer_ratio", 0.0)


@dataclass
class MimeStat:
    """按响应 MIME 类型聚合的统计项。"""

    mime_type: str
    requests: int = 0
    transfer_bytes: int = 0
    uncompressed_bytes: int = 0
    saving_bytes: int = 0

    @property
    def saving_ratio(self) -> float:
        """压缩节省比例（0~1）。"""
        return _ratio(self.saving_bytes, self.uncompressed_bytes)


@dataclass
class DuplicateGroup:
    """一组「同方法 + 同 URL」的重复请求。"""

    method: str
    url: str
    count: int = 0
    transfer_bytes: int = 0
    entries: List[HarEntry] = field(default_factory=list)

    @property
    def wasted_bytes(self) -> int:
        """重复发起造成的冗余传输字节（保留首次，其余视为浪费）。"""
        return int(self.transfer_bytes / max(self.count, 1) * (self.count - 1))


@dataclass
class PageStat:
    """单个页面的加载概览。"""

    page_id: str
    title: str
    requests: int = 0
    transfer_bytes: int = 0
    on_content_load_ms: Optional[float] = None
    on_load_ms: Optional[float] = None
    duration_ms: float = 0.0


@dataclass
class WaterfallRow:
    """瀑布图的一行数据。"""

    entry: HarEntry
    offset_ms: float
    duration_ms: float
    phases: List[Tuple[str, float]] = field(default_factory=list)

    @property
    def end_ms(self) -> float:
        """该行的结束偏移（毫秒）。"""
        return self.offset_ms + self.duration_ms


#: 瀑布图分段配色（PHASE_COLORS 供导出 SVG/HTML 复用）。
PHASE_COLORS: Dict[str, str] = {
    "blocked": "#8A94A6",
    "dns": "#4C9AFF",
    "connect": "#5E6AD2",
    "ssl": "#B27DFF",
    "send": "#2FBF71",
    "wait": "#FFCB3A",
    "receive": "#FF7A45",
}

#: 瀑布图分段的中文说明。
PHASE_LABELS: Dict[str, str] = {
    "blocked": "阻塞排队",
    "dns": "DNS 解析",
    "connect": "TCP 握手",
    "ssl": "TLS 握手",
    "send": "请求发送",
    "wait": "等待首字节",
    "receive": "内容下载",
}

PHASE_ORDER: Tuple[str, ...] = ("blocked", "dns", "connect", "ssl", "send", "wait", "receive")


@dataclass
class HarAnalysis:
    """一次完整 HAR 会话的聚合分析结果。

    典型用法::

        >>> analysis = harscope.analyze(har)
        >>> analysis.total_requests, analysis.total_bytes
        (37, 421963)
    """

    har: Har
    entries: Sequence[HarEntry] = field(default_factory=tuple)
    notes: List[str] = field(default_factory=list)

    # ---- 基础规模 -------------------------------------------------------
    @property
    def total_requests(self) -> int:
        """请求总数。"""
        return len(self.entries)

    @property
    def hosts(self) -> List[str]:
        """去重后的主机列表（按出现顺序）。"""
        seen: Dict[str, None] = {}
        for entry in self.entries:
            if entry.host:
                seen.setdefault(entry.host, None)
        return list(seen)

    @property
    def unique_hosts(self) -> int:
        """去重主机数。"""
        return len(self.hosts)

    @property
    def secure_requests(self) -> int:
        """使用 HTTPS/WSS 的请求数。"""
        return sum(1 for e in self.entries if e.is_secure)

    @property
    def insecure_requests(self) -> int:
        """明文 HTTP/WS 请求数。"""
        return self.total_requests - self.secure_requests

    @property
    def https_ratio(self) -> float:
        """HTTPS 请求占比（0~1）。"""
        return _ratio(self.secure_requests, self.total_requests)

    @property
    def duration_ms(self) -> float:
        """整个会话跨度（毫秒）。"""
        return self.har.wall_clock_ms

    @property
    def duration_s(self) -> float:
        """整个会话跨度（秒）。"""
        return self.duration_ms / 1000.0

    @property
    def total_time_ms(self) -> float:
        """所有请求耗时之和（并发下会远大于 :attr:`duration_ms`）。"""
        return _sum(e.time_ms for e in self.entries)

    @property
    def parallelism(self) -> float:
        """并发度估计：总请求耗时 / 会话跨度。"""
        return _ratio(self.total_time_ms, self.duration_ms)

    # ---- 体积类指标 -----------------------------------------------------
    @property
    def transfer_bytes(self) -> int:
        """线路总传输字节（请求头 + 请求体 + 响应头 + 响应体）。"""
        return int(sum(e.total_size for e in self.entries))

    @property
    def response_bytes(self) -> int:
        """响应侧总传输字节（响应头 + 响应体）。"""
        return int(sum(e.response.total_size for e in self.entries))

    @property
    def body_transfer_bytes(self) -> int:
        """响应体在线路上的总字节数（压缩后）。"""
        return int(sum(e.response.body_transfer_size for e in self.entries))

    @property
    def uncompressed_body_bytes(self) -> int:
        """响应体解压后的总字节数。"""
        return int(sum(e.response.uncompressed_body_size for e in self.entries))

    @property
    def header_bytes(self) -> int:
        """请求头 + 响应头的总字节数。"""
        return int(
            sum(
                e.request.headers_size_or_estimate + e.response.headers_size_or_estimate
                for e in self.entries
            )
        )

    @property
    def compression_saving_bytes(self) -> int:
        """压缩总节省字节数。"""
        return int(sum(e.compression_saving for e in self.entries))

    @property
    def compression_saving_ratio(self) -> float:
        """压缩节省占未压缩总体积的比例（0~1）。"""
        return _ratio(self.compression_saving_bytes, self.uncompressed_body_bytes)

    @property
    def header_ratio(self) -> float:
        """头部字节占总传输的比例（0~1），用于发现「头重脚轻」的问题。"""
        return _ratio(self.header_bytes, self.transfer_bytes)

    # ---- 时间类指标 -----------------------------------------------------
    @property
    def average_ms(self) -> float:
        """平均单请求耗时。"""
        return _ratio(self.total_time_ms, self.total_requests)

    @property
    def p50_ms(self) -> float:
        """请求耗时中位数。"""
        return percentile([e.time_ms for e in self.entries], 0.50)

    @property
    def p95_ms(self) -> float:
        """请求耗时 P95。"""
        return percentile([e.time_ms for e in self.entries], 0.95)

    @property
    def p99_ms(self) -> float:
        """请求耗时 P99。"""
        return percentile([e.time_ms for e in self.entries], 0.99)

    @property
    def average_wait_ms(self) -> float:
        """平均 TTFB（等待首字节）。"""
        return _ratio(_sum(e.wait_ms for e in self.entries), self.total_requests)

    @property
    def p95_wait_ms(self) -> float:
        """TTFB 的 P95。"""
        return percentile([e.wait_ms for e in self.entries], 0.95)

    # ---- 状态分布 -------------------------------------------------------
    @property
    def status_classes(self) -> Dict[str, int]:
        """状态码大类计数，如 ``{'2xx': 30, '3xx': 2, '4xx': 1}``。"""
        result: Dict[str, int] = {}
        for entry in self.entries:
            key = entry.response.status_class
            result[key] = result.get(key, 0) + 1
        return result

    @property
    def status_codes(self) -> Dict[int, int]:
        """精确状态码计数。"""
        result: Dict[int, int] = {}
        for entry in self.entries:
            result[entry.response.status] = result.get(entry.response.status, 0) + 1
        return result

    @property
    def error_entries(self) -> List[HarEntry]:
        """所有 5xx 请求的完整记录。"""
        return [e for e in self.entries if 500 <= e.response.status < 600]

    @property
    def client_error_entries(self) -> List[HarEntry]:
        """所有 4xx 请求的完整记录。"""
        return [e for e in self.entries if 400 <= e.response.status < 500]

    @property
    def success_ratio(self) -> float:
        """2xx/3xx 请求占比（0~1）。"""
        ok = sum(
            1 for e in self.entries if 200 <= e.response.status < 400 or e.response.status == 0
        )
        return _ratio(ok, self.total_requests)

    # ---- 缓存与重复 -----------------------------------------------------
    @property
    def cache_hits(self) -> int:
        """缓存命中条目数。"""
        return sum(1 for e in self.entries if e.is_cache_hit)

    @property
    def cache_hit_ratio(self) -> float:
        """缓存命中率（0~1）。"""
        return _ratio(self.cache_hits, self.total_requests)

    @property
    def not_modified(self) -> List[HarEntry]:
        """返回 304 Not Modified 的请求。"""
        return [e for e in self.entries if e.response.status == 304]

    # ---- 排序查询 -------------------------------------------------------
    def slowest(self, top: int = DEFAULT_TOP, *, by: str = "time") -> List[HarEntry]:
        """返回最慢的若干请求。

        :param top: 返回条数。
        :param by: ``time`` 按总耗时排序，``wait`` 按 TTFB 排序。
        """
        key = (lambda e: e.wait_ms) if by == "wait" else (lambda e: e.time_ms)
        return sorted(self.entries, key=key, reverse=True)[:top]

    def largest(self, top: int = DEFAULT_TOP) -> List[HarEntry]:
        """返回传输体积最大的若干请求。"""
        return sorted(self.entries, key=lambda e: e.total_size, reverse=True)[:top]

    def domain_stats(self, top: int = DEFAULT_TOP) -> List[DomainStat]:
        """按域名聚合统计，按传输体积降序。"""
        buckets: Dict[str, DomainStat] = {}
        for entry in self.entries:
            host = entry.host or "(未知主机)"
            stat = buckets.setdefault(host, DomainStat(host=host))
            stat.requests += 1
            stat.transfer_bytes += entry.total_size
            stat.body_bytes += entry.response.body_transfer_size
            stat.header_bytes += (
                entry.request.headers_size_or_estimate + entry.response.headers_size_or_estimate
            )
            stat.total_ms += entry.time_ms
            stat.wait_ms += entry.wait_ms
            stat.errors += 1 if entry.response.status >= 400 else 0
            if not entry.is_secure:
                stat.secure = False
        ordered = sorted(buckets.values(), key=lambda s: s.transfer_bytes, reverse=True)
        whole = float(self.transfer_bytes) or 1.0
        for stat in ordered:
            setattr(stat, "_transfer_ratio", stat.transfer_bytes / whole)
        return ordered[:top]

    def mime_stats(self, top: int = DEFAULT_TOP) -> List[MimeStat]:
        """按 MIME 类型聚合统计，按传输体积降序。"""
        buckets: Dict[str, MimeStat] = {}
        for entry in self.entries:
            mime = entry.response.mime_type or "(未声明)"
            stat = buckets.setdefault(mime, MimeStat(mime_type=mime))
            stat.requests += 1
            stat.transfer_bytes += entry.response.body_transfer_size
            stat.uncompressed_bytes += entry.response.uncompressed_body_size
            stat.saving_bytes += entry.compression_saving
        return sorted(buckets.values(), key=lambda s: s.transfer_bytes, reverse=True)[:top]

    def duplicates(self, min_count: int = 2, top: int = DEFAULT_TOP) -> List[DuplicateGroup]:
        """识别完全重复的请求（同方法 + 同 URL，忽略 query 顺序以外的差异）。

        :param min_count: 至少出现几次才算重复。
        :param top: 返回组数上限。
        """
        buckets: Dict[Tuple[str, str], DuplicateGroup] = {}
        for entry in self.entries:
            key = (entry.request.method, entry.request.url)
            group = buckets.setdefault(
                key, DuplicateGroup(method=entry.request.method, url=entry.request.url)
            )
            group.count += 1
            group.transfer_bytes += entry.total_size
            group.entries.append(entry)
        candidates = [g for g in buckets.values() if g.count >= min_count]
        return sorted(candidates, key=lambda g: (g.count, g.transfer_bytes), reverse=True)[:top]

    def redirect_chains(self, top: int = DEFAULT_TOP) -> List[HarEntry]:
        """返回触发重定向的条目（3xx 响应）。"""
        chains = [e for e in self.entries if e.response.is_redirect]
        return sorted(chains, key=lambda e: e.started_ms)[:top]

    def waterfall(self, *, limit: int = 40, sort_by_start: bool = True) -> List[WaterfallRow]:
        """计算瀑布图数据。

        :param limit: 最多返回多少行（按耗时排序截取）。
        :param sort_by_start: 是否按开始时间重排；关闭则保留原始顺序。
        """
        rows: List[WaterfallRow] = []
        for entry in self.entries:
            durations = [
                (phase, float(getattr(entry.timings, phase) or 0.0))
                for phase in PHASE_ORDER
            ]
            known = sum(value for _, value in durations)
            if not entry.timings.has_detail or known <= 0:
                durations = [("receive", float(entry.time_ms or 0.0))]
                if entry.timings.wait:
                    durations = [
                        ("wait", float(entry.timings.wait)),
                        ("receive", max(0.0, entry.time_ms - entry.timings.wait)),
                    ]
            phases = [(name, value) for name, value in durations if value > 0]
            rows.append(
                WaterfallRow(
                    entry=entry,
                    offset_ms=0.0,
                    duration_ms=float(entry.time_ms or 0.0),
                    phases=phases,
                )
            )
        if rows:
            base = min(e.started_ms for e in self.entries if e.started_date_time) if any(
                e.started_date_time for e in self.entries
            ) else 0.0
            for entry, row in zip(self.entries, rows):
                row.offset_ms = max(0.0, entry.started_ms - base)
        if sort_by_start:
            rows.sort(key=lambda r: (r.offset_ms, r.entry.index))
        if limit and len(rows) > limit:
            rows = sorted(rows, key=lambda r: r.duration_ms, reverse=True)[:limit]
            rows.sort(key=lambda r: r.offset_ms)
        return rows

    def page_stats(self) -> List[PageStat]:
        """按 ``pageref`` 维度汇总页面加载情况。"""
        pages = {p.id: p for p in self.har.pages}
        result: Dict[str, PageStat] = {}
        for page in self.har.pages:
            result[page.id] = PageStat(
                page_id=page.id,
                title=page.title or page.id or "(未命名页面)",
                on_content_load_ms=page.on_content_load_ms,
                on_load_ms=page.on_load_ms,
            )
        for entry in self.entries:
            key = entry.pageref or "(未归属)"
            stat = result.get(key)
            if stat is None:
                meta = pages.get(key)
                stat = PageStat(
                    page_id=key,
                    title=(meta.title if meta and meta.title else key),
                    on_content_load_ms=meta.on_content_load_ms if meta else None,
                    on_load_ms=meta.on_load_ms if meta else None,
                )
                result[key] = stat
            stat.requests += 1
            stat.transfer_bytes += entry.total_size
        for key, stat in result.items():
            members = [e for e in self.entries if (e.pageref or "(未归属)") == key]
            if members:
                stamps = [e.started_ms + e.time_ms for e in members if e.started_date_time]
                starts = [e.started_ms for e in members if e.started_date_time]
                if stamps and starts:
                    stat.duration_ms = max(0.0, max(stamps) - min(starts))
                else:
                    stat.duration_ms = _sum(e.time_ms for e in members)
        return list(result.values())

    def summary_dict(self) -> Dict[str, Any]:
        """把核心指标打包成可 JSON 序列化的字典，供导出层复用。"""
        return {
            "source": self.har.source,
            "title": self.har.title,
            "har_version": self.har.version,
            "creator": " ".join(
                part for part in (self.har.creator_name, self.har.creator_version) if part
            )
            or "未知",
            "requests": self.total_requests,
            "hosts": self.unique_hosts,
            "duration_ms": round(self.duration_ms, 2),
            "total_time_ms": round(self.total_time_ms, 2),
            "transfer_bytes": self.transfer_bytes,
            "body_transfer_bytes": self.body_transfer_bytes,
            "uncompressed_body_bytes": self.uncompressed_body_bytes,
            "header_bytes": self.header_bytes,
            "compression_saving_bytes": self.compression_saving_bytes,
            "compression_saving_ratio": round(self.compression_saving_ratio, 4),
            "https_ratio": round(self.https_ratio, 4),
            "cache_hit_ratio": round(self.cache_hit_ratio, 4),
            "avg_ms": round(self.average_ms, 2),
            "p50_ms": round(self.p50_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "avg_wait_ms": round(self.average_wait_ms, 2),
            "parallelism": round(self.parallelism, 2),
            "status_classes": self.status_classes,
            "notes": list(self.notes),
        }


def analyze(har: Har) -> HarAnalysis:
    """对一个 :class:`~harscope.model.Har` 做全量分析。

    :param har: 已解析的 HAR 会话。
    :returns: :class:`HarAnalysis` 实例。
    """
    entries = list(har.entries)
    notes: List[str] = list(har.warnings)

    measured = [e for e in entries if (e.timings.wait is not None or e.timings.send is not None)]
    if entries and len(measured) < len(entries) / 2:
        notes.append("半数以上记录缺少分段耗时，TTFB 由总耗时近似代替")

    if entries and all(e.response.transfer_size is None and e.response.body_size is None
                       for e in entries):
        notes.append("缺少传输体积字段，体积指标基于 content.size 估算，仅作参考")

    return HarAnalysis(har=har, entries=tuple(entries), notes=notes)
