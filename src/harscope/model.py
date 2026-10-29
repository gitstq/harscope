"""对 HAR 1.2（HTTP Archive）记录的纯数据建模。

设计目标
--------
1. **完全容错**：真实世界的 HAR 由 Chrome DevTools、Charles、Fiddler、mitmproxy、
   Safari Web Inspector、爬虫自采等不同工具产出，几乎每个字段都可能缺失、为 ``-1``
   或类型漂移。本模块把所有未知量统一建模为 ``None``，绝不在解析期抛异常。
2. **只依赖标准库**：不使用 pydantic / attrs，纯 ``dataclasses`` 实现，零成本。
3. **面向分析**：把「行数」「耗时」「体积」等派生值做成惰性属性，
   上层 :mod:`harscope.analyze` 无需重复处理脏数据。

字段含义遵循 <http://www.softwareishard.com/blog/har-12-spec/>。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit

__all__ = [
    "HarHeader",
    "HarCookie",
    "HarRequest",
    "HarResponse",
    "HarTimings",
    "HarEntry",
    "HarPage",
    "Har",
]


def _as_float(value: Any, *, negative_is_none: bool = False) -> Optional[float]:
    """把任意输入安全地转成 ``float``。

    :param value: 原始字段值，可能是数字、字符串或 ``None``。
    :param negative_is_none: HAR 规范用 ``-1`` 表示「未知」，设为 ``True`` 时
        会把负值归一化为 ``None``。
    :returns: 归一化后的浮点数，无法转换时返回 ``None``。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if negative_is_none and number < 0:
        return None
    return number


def _as_int(value: Any, *, negative_is_none: bool = False) -> Optional[int]:
    """把任意输入安全地转成 ``int``，语义同 :func:`_as_float`。"""
    number = _as_float(value, negative_is_none=negative_is_none)
    if number is None:
        return None
    return int(number)


def _as_str(value: Any, default: str = "") -> str:
    """把任意输入转成字符串，``None`` 归一化为 ``default``。"""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _as_list(value: Any) -> List[Any]:
    """保证返回列表（脏数据中常见把数组写成 dict / None 的情况）。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return list(value.values())
    return [value]


@dataclass(frozen=True)
class HarHeader:
    """单个 HTTP 头字段。"""

    name: str
    value: str

    @property
    def lower_name(self) -> str:
        """小写形式的字段名，用于大小写不敏感查找。"""
        return self.name.lower()

    @property
    def wire_size(self) -> int:
        """该字段在 HTTP/1.x 报文中占用的近似字节数（``name: value\\r\\n``）。"""
        return len(self.name.encode("utf-8", "replace")) + len(
            self.value.encode("utf-8", "replace")
        ) + 4


@dataclass(frozen=True)
class HarCookie:
    """单个 Cookie 条目。"""

    name: str
    value: str
    secure: bool = False
    http_only: bool = False
    same_site: Optional[str] = None
    expires: Optional[str] = None
    path: Optional[str] = None
    domain: Optional[str] = None


@dataclass(frozen=True)
class HarTimings:
    """一条请求的网络分段耗时（单位：毫秒）。

    规范允许用 ``-1`` 表示该段「不适用 / 未知」，这里统一转成 ``None``。
    常见分段含义：

    ``blocked``  等待可用 TCP 连接的排队阻塞时间
    ``dns``      DNS 解析耗时
    ``connect``  TCP 三次握手耗时
    ``ssl``      TLS 握手耗时（HTTP 请求为 ``None``）
    ``send``     发送请求报文耗时
    ``wait``     等待首字节（TTFB，不含网络传输）
    ``receive``  读取响应体耗时
    """

    blocked: Optional[float] = None
    dns: Optional[float] = None
    connect: Optional[float] = None
    ssl: Optional[float] = None
    send: Optional[float] = None
    wait: Optional[float] = None
    receive: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Any) -> "HarTimings":
        """从任意脏数据来源构造对象，字段缺失不影响实例化。"""
        if not isinstance(data, dict):
            return cls()
        return cls(
            blocked=_as_float(data.get("blocked"), negative_is_none=True),
            dns=_as_float(data.get("dns"), negative_is_none=True),
            connect=_as_float(data.get("connect"), negative_is_none=True),
            ssl=_as_float(data.get("ssl"), negative_is_none=True),
            send=_as_float(data.get("send"), negative_is_none=True),
            wait=_as_float(data.get("wait"), negative_is_none=True),
            receive=_as_float(data.get("receive"), negative_is_none=True),
        )

    @property
    def total(self) -> float:
        """各分段之和。**注意**：可能与 :attr:`HarEntry.time` 不一致。

        很多采集器会略写分段数据，因此取值以 ``entry.time`` 为准，
        本值只在分段完整时用于交叉校验。
        """
        return float(
            sum(v for v in (self.blocked, self.dns, self.connect, self.ssl,
                            self.send, self.wait, self.receive) if v is not None)
        )

    @property
    def has_detail(self) -> bool:
        """是否存在任何非零分段数据（决定能否绘制精细瀑布图）。"""
        return any(
            v is not None and v > 0
            for v in (self.blocked, self.dns, self.connect, self.ssl,
                      self.send, self.wait, self.receive)
        )


@dataclass
class HarRequest:
    """一条 HAR 记录中的请求部分。"""

    method: str = "GET"
    url: str = ""
    http_version: str = "HTTP/1.1"
    headers: List[HarHeader] = field(default_factory=list)
    cookies: List[HarCookie] = field(default_factory=list)
    query_string: List[Tuple[str, str]] = field(default_factory=list)
    headers_size: Optional[int] = None
    body_size: Optional[int] = None
    post_data_mime_type: Optional[str] = None
    post_data_size: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Any) -> "HarRequest":
        """容错构造：任何字段缺失都以安全的默认值兜底。"""
        data = data if isinstance(data, dict) else {}
        headers = [
            HarHeader(name=_as_str(h.get("name")), value=_as_str(h.get("value")))
            for h in _as_list(data.get("headers"))
            if isinstance(h, dict)
        ]
        cookies = [
            HarCookie(
                name=_as_str(c.get("name")),
                value=_as_str(c.get("value")),
                secure=bool(c.get("secure")),
                http_only=bool(c.get("httpOnly")),
                same_site=c.get("sameSite"),
            )
            for c in _as_list(data.get("cookies"))
            if isinstance(c, dict)
        ]
        query = []
        for q in _as_list(data.get("queryString")):
            if isinstance(q, dict):
                query.append((_as_str(q.get("name")), _as_str(q.get("value"))))
        post = data.get("postData") if isinstance(data.get("postData"), dict) else {}
        return cls(
            method=_as_str(data.get("method"), "GET").upper() or "GET",
            url=_as_str(data.get("url")),
            http_version=_as_str(data.get("httpVersion"), "HTTP/1.1"),
            headers=headers,
            cookies=cookies,
            query_string=query,
            headers_size=_as_int(data.get("headersSize"), negative_is_none=True),
            body_size=_as_int(data.get("bodySize"), negative_is_none=True),
            post_data_mime_type=(post.get("mimeType") or None) if post else None,
            post_data_size=_as_int(post.get("size"), negative_is_none=True) if post else None,
        )

    def header(self, name: str) -> Optional[str]:
        """按大小写不敏感方式读取指定请求头，未命中返回 ``None``。"""
        lowered = name.lower()
        for item in self.headers:
            if item.lower_name == lowered:
                return item.value
        return None

    @property
    def estimated_headers_size(self) -> int:
        """估算请求行 + 头部字节数。

        当采集器未给出 ``headersSize``（或为 ``-1``）时使用，保证
        「头部 vs 实体」占比分析依然可用。
        """
        request_line = len(
            ("%s %s %s\r\n" % (self.method, self.path_with_query, self.http_version))
            .encode("utf-8", "replace")
        )
        return request_line + sum(h.wire_size for h in self.headers)

    @property
    def headers_size_or_estimate(self) -> int:
        """优先使用真实 ``headersSize``，缺失时回退到估算值。"""
        return self.headers_size if self.headers_size is not None else self.estimated_headers_size

    @property
    def split(self) -> Any:
        """``urlsplit`` 的结果缓存（``scheme/netloc/path/query/fragment``）。"""
        return urlsplit(self.url)

    @property
    def scheme(self) -> str:
        """URL 协议，如 ``https``。"""
        return (self.split.scheme or "").lower()

    @property
    def host(self) -> str:
        """主机名（含端口若无默认端口），小写。"""
        return (self.split.hostname or "").lower()

    @property
    def port(self) -> int:
        """推导出的端口号（URL 未显式指定时按协议取默认值 80/443）。"""
        try:
            if self.split.port:
                return int(self.split.port)
        except ValueError:
            pass
        return 443 if self.scheme == "https" else 80

    @property
    def path(self) -> str:
        """URL 路径部分（不含 query / fragment）。"""
        return self.split.path or "/"

    @property
    def path_with_query(self) -> str:
        """URL 路径 + query 部分（不含 scheme / host / fragment）。"""
        parts = self.split
        query = ("?" + parts.query) if parts.query else ""
        return (parts.path or "/") + query

    @property
    def is_secure(self) -> bool:
        """是否走 HTTPS / WSS 等加密协议。"""
        return self.scheme in {"https", "wss"}

    @property
    def base_url(self) -> str:
        """去掉 query 与 fragment 后的规范化地址，用于重复请求识别。"""
        parts = self.split
        return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))

    @property
    def display_path(self) -> str:
        """适合终端展示的短路径，超过 68 字符做中部省略。"""
        text = self.path_with_query
        return text if len(text) <= 68 else text[:44] + "…" + text[-23:]

    @property
    def has_request_body(self) -> bool:
        """是否携带请求体（POST/PUT/PATCH 等）。"""
        if self.post_data_size:
            return True
        return (self.body_size or 0) > 0 and self.method not in {"GET", "HEAD"}


@dataclass
class HarResponse:
    """一条 HAR 记录中的响应部分。"""

    status: int = 0
    status_text: str = ""
    http_version: str = "HTTP/1.1"
    headers: List[HarHeader] = field(default_factory=list)
    cookies: List[HarCookie] = field(default_factory=list)
    headers_size: Optional[int] = None
    body_size: Optional[int] = None
    transfer_size: Optional[int] = None
    content_size: Optional[int] = None
    compression: Optional[int] = None
    mime_type: str = ""
    redirect_url: str = ""
    body_encoding: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any) -> "HarResponse":
        """容错构造：缺失字段一律用安全默认值兜底。"""
        data = data if isinstance(data, dict) else {}
        headers = [
            HarHeader(name=_as_str(h.get("name")), value=_as_str(h.get("value")))
            for h in _as_list(data.get("headers"))
            if isinstance(h, dict)
        ]
        cookies = [
            HarCookie(
                name=_as_str(c.get("name")),
                value=_as_str(c.get("value")),
                secure=bool(c.get("secure")),
                http_only=bool(c.get("httpOnly")),
                same_site=c.get("sameSite"),
            )
            for c in _as_list(data.get("cookies"))
            if isinstance(c, dict)
        ]
        content = data.get("content") if isinstance(data.get("content"), dict) else {}
        return cls(
            status=_as_int(data.get("status")) or 0,
            status_text=_as_str(data.get("statusText")),
            http_version=_as_str(data.get("httpVersion"), "HTTP/1.1"),
            headers=headers,
            cookies=cookies,
            headers_size=_as_int(data.get("headersSize"), negative_is_none=True),
            body_size=_as_int(data.get("bodySize"), negative_is_none=True),
            transfer_size=_as_int(data.get("_transferSize"), negative_is_none=True),
            content_size=_as_int(content.get("size"), negative_is_none=True),
            compression=_as_int(content.get("compression"), negative_is_none=True),
            mime_type=_as_str(content.get("mimeType")),
            redirect_url=_as_str(data.get("redirectURL")),
            body_encoding=content.get("encoding") or None,
        )

    def header(self, name: str) -> Optional[str]:
        """按大小写不敏感方式读取响应头，未命中返回 ``None``。"""
        lowered = name.lower()
        for item in self.headers:
            if item.lower_name == lowered:
                return item.value
        return None

    @property
    def estimated_headers_size(self) -> int:
        """估算状态行 + 头部字节数。"""
        status_line = len(
            ("%s %d %s\r\n" % (self.http_version, self.status, self.status_text))
            .encode("utf-8", "replace")
        )
        return status_line + sum(h.wire_size for h in self.headers)

    @property
    def headers_size_or_estimate(self) -> int:
        """优先使用真实 ``headersSize``，否则回退估算值。"""
        return self.headers_size if self.headers_size is not None else self.estimated_headers_size

    @property
    def uncompressed_body_size(self) -> int:
        """解压后的响应体字节数；未知时退回到 ``bodySize`` / 0。"""
        if self.content_size is not None:
            return self.content_size
        return self.body_size or 0

    @property
    def body_transfer_size(self) -> int:
        """线路上实际传输的响应体字节数（含压缩开销）。

        优先级：``_transferSize``（Chrome 提供，最准）→
        ``bodySize``（多为透传字节数）→ ``content.size``（未解压）。
        """
        if self.transfer_size is not None:
            return self.transfer_size
        if self.body_size is not None:
            return self.body_size
        return self.uncompressed_body_size

    @property
    def total_size(self) -> int:
        """该响应在线路上的总字节数（头部 + 实体）。"""
        return self.headers_size_or_estimate + self.body_transfer_size

    @property
    def compression_saving(self) -> int:
        """相对未压缩体积节省的字节数（负值说明存在压缩或计算误差）。"""
        return self.uncompressed_body_size - self.body_transfer_size

    @property
    def is_redirect(self) -> bool:
        """是否为 3xx 重定向响应。"""
        return 300 <= self.status < 400

    @property
    def status_class(self) -> str:
        """状态码归类字符串，如 ``2xx`` / ``4xx`` / ``other``。"""
        if 100 <= self.status < 600:
            return "%dxx" % (self.status // 100)
        return "other"


@dataclass
class HarEntry:
    """一条完整的请求-响应记录。"""

    index: int = 0
    started_date_time: Optional[datetime] = None
    time_ms: float = 0.0
    request: HarRequest = field(default_factory=HarRequest)
    response: HarResponse = field(default_factory=HarResponse)
    timings: HarTimings = field(default_factory=HarTimings)
    cache_before: Dict[str, Any] = field(default_factory=dict)
    cache_after: Dict[str, Any] = field(default_factory=dict)
    server_ip_address: str = ""
    connection: str = ""
    pageref: str = ""
    resource_type: Optional[str] = None
    comment: str = ""

    @classmethod
    def from_dict(cls, data: Any, index: int = 0) -> "HarEntry":
        """容错构造单条 HAR 记录。"""
        data = data if isinstance(data, dict) else {}
        cache = data.get("cache") if isinstance(data.get("cache"), dict) else {}
        before = cache.get("beforeRequest") if isinstance(cache.get("beforeRequest"), dict) else {}
        after = cache.get("afterRequest") if isinstance(cache.get("afterRequest"), dict) else {}
        return cls(
            index=index,
            started_date_time=parse_date(data.get("startedDateTime")),
            time_ms=_as_float(data.get("time")) or 0.0,
            request=HarRequest.from_dict(data.get("request")),
            response=HarResponse.from_dict(data.get("response")),
            timings=HarTimings.from_dict(data.get("timings")),
            cache_before=before,
            cache_after=after,
            server_ip_address=_as_str(data.get("serverIPAddress")),
            connection=_as_str(data.get("connection")),
            pageref=_as_str(data.get("pageref")),
            resource_type=data.get("_resourceType") or None,
            comment=_as_str(data.get("comment")),
        )

    @property
    def started_ms(self) -> float:
        """起始时间（毫秒，POSIX 时间戳 × 1000）；无时间戳时用 0.0。"""
        return epoch_ms(self.started_date_time) if self.started_date_time else 0.0

    @property
    def url(self) -> str:
        """完整请求 URL。"""
        return self.request.url

    @property
    def host(self) -> str:
        """请求主机名。"""
        return self.request.host or _fallback_host(self.request.url)

    @property
    def is_secure(self) -> bool:
        """请求是否使用加密协议。"""
        return self.request.is_secure

    @property
    def total_size(self) -> int:
        """该条目在线路上的总字节数（请求头+请求体+响应头+响应体）。"""
        return (
            self.request.headers_size_or_estimate
            + (self.request.body_size or 0)
            + self.response.total_size
        )

    @property
    def wait_ms(self) -> float:
        """等待首字节时间（TTFB）。缺乏分段数据时退回总耗时。"""
        if self.timings.wait is not None:
            return self.timings.wait
        return self.time_ms

    @property
    def is_cache_hit(self) -> bool:
        """是否被本地磁盘/内存缓存命中。

        判定依据：``cache.beforeRequest`` 存在且 ``hitCount > 0``，
        或 ``afterRequest`` 中标记为已存在缓存条目。
        """
        try:
            if int(self.cache_before.get("hitCount") or 0) > 0:
                return True
        except (TypeError, ValueError):
            pass
        if self.cache_before.get("expires") or self.cache_before.get("lastAccess"):
            return True
        return False

    @property
    def compression_saving(self) -> int:
        """该条目相对未压缩体积节省的字节数。"""
        return self.response.compression_saving

    @property
    def label(self) -> str:
        """终端展示用的简短标识（``方法 主机/短路径``）。"""
        return "%s %s%s" % (self.request.method, self.host, self.request.display_path)


@dataclass
class HarPage:
    """HAR 中的页面（``pages`` 节点）信息。"""

    id: str = ""
    title: str = ""
    started_date_time: Optional[datetime] = None
    on_content_load_ms: Optional[float] = None
    on_load_ms: Optional[float] = None
    comment: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "HarPage":
        """容错构造页面记录。"""
        data = data if isinstance(data, dict) else {}
        timings = data.get("pageTimings") if isinstance(data.get("pageTimings"), dict) else {}
        return cls(
            id=_as_str(data.get("id")),
            title=_as_str(data.get("title")),
            started_date_time=parse_date(data.get("startedDateTime")),
            on_content_load_ms=_as_float(timings.get("onContentLoad"), negative_is_none=True),
            on_load_ms=_as_float(timings.get("onLoad"), negative_is_none=True),
            comment=_as_str(data.get("comment")),
        )


@dataclass
class Har:
    """一个完整的 HAR 会话。"""

    version: str = "1.2"
    creator_name: str = ""
    creator_version: str = ""
    browser_name: str = ""
    browser_version: str = ""
    comment: str = ""
    pages: List[HarPage] = field(default_factory=list)
    entries: List[HarEntry] = field(default_factory=list)
    source: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def entry_count(self) -> int:
        """条目总数。"""
        return len(self.entries)

    @property
    def start_time(self) -> Optional[datetime]:
        """会话中最早的一条请求时间。"""
        stamps = [e.started_date_time for e in self.entries if e.started_date_time]
        if self.pages:
            stamps += [p.started_date_time for p in self.pages if p.started_date_time]
        return min(stamps) if stamps else None

    @property
    def end_time(self) -> Optional[datetime]:
        """会话中最后一条请求的完成时间。"""
        stamps = [
            e.started_date_time
            for e in self.entries
            if e.started_date_time
        ]
        return max(stamps) if stamps else None

    @property
    def wall_clock_ms(self) -> float:
        """会话总跨度（毫秒），按「最晚完成时间 - 最早开始时间」计算。"""
        stamps = [
            (e.started_ms, e.started_ms + e.time_ms)
            for e in self.entries
            if e.started_date_time
        ]
        if not stamps:
            return sum(e.time_ms for e in self.entries)
        start = min(s for s, _ in stamps)
        end = max(e for _, e in stamps)
        return max(0.0, end - start)

    @property
    def title(self) -> str:
        """可读标题：优先页面标题，其次采集器名，最后文件名。"""
        for page in self.pages:
            if page.title:
                return page.title
        if self.creator_name:
            return "%s %s" % (self.creator_name, self.creator_version or "").strip()
        return self.source or "未命名会话"

    def entries_for_page(self, page_id: str) -> List[HarEntry]:
        """按 ``pageref`` 过滤属于指定页面的条目。"""
        return [e for e in self.entries if e.pageref == page_id]


def parse_date(value: Any) -> Optional[datetime]:
    """解析 HAR 的 ISO-8601 时间字符串。

    支持 ``Z`` 后缀、带/不带毫秒、任意 UTC 偏移；失败返回 ``None``
    （绝不在解析期抛异常，只依赖 :func:`datetime.fromisoformat` 的兼容模式）。
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = _as_str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    for candidate in (text, _normalize_offset(text), _strip_fraction(text)):
        if not candidate:
            continue
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return None


def _normalize_offset(text: str) -> str:
    """把 ``+0800`` 形式的偏移量补成 ``+08:00``，提高解析成功率。"""
    import re

    return re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)


def _strip_fraction(text: str) -> str:
    """抹掉秒的小数部分，兼容老旧 Python 时区组合限制。"""
    import re

    return re.sub(r"\.(\d+)", "", text)


def epoch_ms(moment: Optional[datetime]) -> float:
    """把 ``datetime`` 转成毫秒时间戳。"""
    if moment is None:
        return 0.0
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.timestamp() * 1000.0


def _fallback_host(url: str) -> str:
    """在 URL 不合法（缺 scheme 等）时尽力取出主机名。"""
    try:
        parts = urlsplit(url if "//" in url else "//" + url)
        return (parts.hostname or "").lower()
    except ValueError:
        return ""


# ``HarEntry`` / ``HarPage`` 使用可变默认字段，这里允许其参与 ``dataclasses.fields`` 迭代。
dataclasses.fields(HarEntry)  # pragma: no cover - 触发类型解析，无副作用
