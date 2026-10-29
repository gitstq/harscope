"""纯标准库实现的 HAR 录制器 —— 不需要浏览器也能产出 HAR 文件。

大多数 HAR 分析工具只能「读」由 DevTools / Charles 导出的文件，而 HarScope
还能**自己采**：:

    harscope record https://example.com -o trace.har

实现要点：

* 直接用 :mod:`http.client` + :mod:`ssl` 打开连接，手工测量 DNS / TCP / TLS /
  发送 / 首字节 / 下载各阶段耗时，因此瀑布图数据是真实分段的；
* 支持自动跟随重定向（每跳产生独立条目，方便分析跳转链开销）；
* 支持对 HTML 页面做一级资源抓取（``--assets``），让瀑布图更接近真实加载；
* **默认只记录元数据和体积，绝不保存响应体内容**，避免把敏感数据写进 HAR。

出于安全考虑，录制器不跟随跨主机无限跳转、不执行 JS、不满链路递归。
"""

from __future__ import annotations

import gzip
import http.client
import socket
import ssl
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

from .exceptions import NetworkRecordError

__all__ = ["RecordOptions", "record", "har_template", "DEFAULT_USER_AGENT"]

#: 默认 UA，方便服务端识别这是自动化分析流量。
DEFAULT_USER_AGENT = "HarScope/%s (+https://github.com/gitstq/harscope)" % "1.0.0"

#: 单个请求默认超时（秒）。
DEFAULT_TIMEOUT = 10.0

#: 默认跟随的最大重定向次数。
DEFAULT_MAX_REDIRECTS = 5

#: 需要抓取属性的 HTML 标签映射：标签 -> 属性列表。
_ASSET_ATTRS: Dict[str, Tuple[str, ...]] = {
    "script": ("src",),
    "link": ("href",),
    "img": ("src", "srcset"),
    "source": ("src", "srcset"),
    "iframe": ("src",),
    "audio": ("src",),
    "video": ("src",),
    "track": ("src",),
}

#: ``link[rel]`` 只保留这些类型，避免把 favicon / preconnect 全拉下来。
_STYLESHEET_RELS = {"stylesheet", "preload"}


@dataclass
class RecordOptions:
    """录制行为配置。"""

    timeout: float = DEFAULT_TIMEOUT
    max_redirects: int = DEFAULT_MAX_REDIRECTS
    max_assets: int = 12
    user_agent: str = DEFAULT_USER_AGENT
    headers: Dict[str, str] = field(default_factory=dict)
    insecure: bool = False
    follow_redirects: bool = True
    same_host_only: bool = True

    def request_headers(self) -> Dict[str, str]:
        """构造默认请求头集合。"""
        base = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
        }
        base.update(self.headers)
        return base


@dataclass
class _PhaseClock:
    """一次请求的分段耗时容器（单位：毫秒）。"""

    dns: Optional[float] = None
    connect: Optional[float] = None
    ssl: Optional[float] = None
    send: Optional[float] = None
    wait: Optional[float] = None
    receive: Optional[float] = None


class _MeteredConnection(http.client.HTTPConnection):
    """带分段计时的 HTTP 连接。

    覆写 :meth:`connect` 自己完成 DNS / TCP / TLS，
    既拿到了精确耗时，又不改变 http.client 的上层行为。
    """

    def __init__(self, host: str, port: int, *, clock: _PhaseClock,
                 timeout: float = DEFAULT_TIMEOUT, use_tls: bool = False,
                 insecure: bool = False) -> None:
        super().__init__(host, port, timeout=timeout)
        self._clock = clock
        self._use_tls = use_tls
        self._insecure = insecure

    def connect(self) -> None:  # noqa: D102 - 覆写标准库方法
        started = time.perf_counter()
        try:
            infos = socket.getaddrinfo(self.host, self.port, 0, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise NetworkRecordError("DNS 解析失败 %s：%s" % (self.host, exc)) from exc
        self._clock.dns = (time.perf_counter() - started) * 1000.0

        family, socktype, proto, _canon, address = infos[0]
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(self.timeout)
        handshake_started = time.perf_counter()
        try:
            sock.connect(address)
        except OSError as exc:
            sock.close()
            raise NetworkRecordError("连接失败 %s:%s：%s" % (self.host, self.port, exc)) from exc
        tcp_done = time.perf_counter()
        self._clock.connect = (tcp_done - handshake_started) * 1000.0

        if self._use_tls:
            context = ssl.create_default_context()
            if self._insecure:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            tls_started = time.perf_counter()
            try:
                sock = context.wrap_socket(sock, server_hostname=self.host)
            except ssl.SSLError as exc:
                sock.close()
                raise NetworkRecordError("TLS 握手失败 %s：%s" % (self.host, exc)) from exc
            self._clock.ssl = (time.perf_counter() - tls_started) * 1000.0
        self.sock = sock


def _decode_body(payload: bytes, encoding: Optional[str]) -> Tuple[bytes, int]:
    """按 Content-Encoding 解压响应体。

    :param payload: 线路原始字节。
    :param encoding: ``content-encoding`` 的值。
    :returns: ``(解压后的字节, 解压后长度)``；解压失败时回退到原始长度。
    """
    if not payload:
        return payload, 0
    if encoding and "gzip" in encoding.lower():
        try:
            plain = gzip.decompress(payload)
            return plain, len(plain)
        except (OSError, zlib.error):
            return payload, len(payload)
    if encoding and "deflate" in encoding.lower():
        try:
            plain = zlib.decompress(payload)
        except zlib.error:
            try:
                plain = zlib.decompress(payload, -zlib.MAX_WBITS)
            except zlib.error:
                return payload, len(payload)
        return plain, len(plain)
    if encoding and "br" in encoding.lower():
        # Python 标准库不带 brotli；如实记录，交由使用者自行安装 brotli 后二次处理
        return payload, len(payload)
    return payload, len(payload)


def _har_headers(pairs: Sequence[Tuple[str, str]]) -> List[Dict[str, str]]:
    """把 ``(name, value)`` 序列转成 HAR 的 headers 结构。"""
    return [{"name": name, "value": value} for name, value in pairs]


def _iso(moment: datetime) -> str:
    """ISO-8601 格式化（带毫秒与 UTC 偏移）。"""
    return moment.astimezone().isoformat(timespec="milliseconds")


class _AssetCollector(HTMLParser):
    """从 HTML 文档中抽取一级静态资源 URL。"""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.assets: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        """只关注可能引用资源的标签。"""
        attributes = {name.lower(): (value or "") for name, value in attrs}
        if tag == "link":
            rel = (attributes.get("rel") or "").lower()
            if rel.split() and rel.split()[0] not in _STYLESHEET_RELS:
                return
        elif tag in ("img", "source") and ("srcset" in attributes):
            self._collect_srcset(attributes.get("srcset", ""))
        for attribute in _ASSET_ATTRS.get(tag, ()):
            value = attributes.get(attribute)
            if not value or value.startswith(("data:", "javascript:", "blob:")):
                continue
            if attribute == "srcset":
                continue
            absolute = urljoin(self.base_url, value)
            if absolute.startswith(("http://", "https://")):
                self.assets.append(absolute)

    def _collect_srcset(self, value: str) -> None:
        """处理 ``srcset`` 的 ``url 1x, url 2x`` 语法，只取第一个候选。"""
        for candidate in value.split(","):
            url = candidate.strip().split(" ")[0]
            if not url:
                continue
            absolute = urljoin(self.base_url, url)
            if absolute.startswith(("http://", "https://")):
                self.assets.append(absolute)
            break


def _fetch_once(
    url: str,
    options: RecordOptions,
    *,
    method: str = "GET",
    referer: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[bytes], Optional[str]]:
    """执行一次 HTTP 请求并产出一条 HAR entry。

    :returns: ``(entry, html_bytes_or_None, final_url)``。
    :raises NetworkRecordError: 网络层不可恢复的错误。
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise NetworkRecordError("不支持的协议：%s" % scheme)
    host = parts.hostname or ""
    if not host:
        raise NetworkRecordError("URL 缺少主机名：%s" % url)
    port = parts.port or (443 if scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query

    request_headers = list(options.request_headers().items())
    if referer:
        request_headers.append(("Referer", referer))

    clock = _PhaseClock()
    started = datetime.now(timezone.utc)
    connection_cls = _MeteredConnection
    connection = connection_cls(
        host,
        port,
        clock=clock,
        timeout=options.timeout,
        use_tls=scheme == "https",
        insecure=options.insecure,
    )
    try:
        wall_started = time.perf_counter()
        send_started = time.perf_counter()
        connection.request(method, path, body=None, headers=dict(request_headers))
        clock.send = (time.perf_counter() - send_started) * 1000.0

        wait_started = time.perf_counter()
        response = connection.getresponse()
        clock.wait = (time.perf_counter() - wait_started) * 1000.0

        receive_started = time.perf_counter()
        raw = response.read()
        content_encoding = response.getheader("content-encoding")
        clock.receive = (time.perf_counter() - receive_started) * 1000.0
        total_ms = (time.perf_counter() - wall_started) * 1000.0

        response_headers = response.getheaders()
        status = response.status
        reason = response.reason
        version = "HTTP/1.1"
        server_ip = ""
        try:
            peername = connection.sock.getpeername() if connection.sock else None
            if peername:
                server_ip = peername[0]
        except OSError:  # pragma: no cover - 连接已关闭
            server_ip = ""
    except (http.client.HTTPException, socket.timeout, OSError) as exc:
        raise NetworkRecordError("请求 %s 失败：%s" % (url, exc)) from exc
    finally:
        try:
            connection.close()
        except Exception:  # pragma: no cover - 关闭失败可忽略
            pass

    plain, plain_size = _decode_body(raw, content_encoding)
    mime_type = (response.getheader("content-type") or "").split(";")[0].strip()

    entry: Dict[str, Any] = {
        "startedDateTime": _iso(started),
        "time": round(total_ms, 3),
        "request": {
            "method": method,
            "url": url,
            "httpVersion": version,
            "cookies": [],
            "headers": _har_headers(request_headers),
            "queryString": [
                {"name": pair.split("=", 1)[0], "value": pair.split("=", 1)[-1]}
                for pair in (parts.query.split("&") if parts.query else [])
                if pair
            ],
            "headersSize": -1,
            "bodySize": 0,
        },
        "response": {
            "status": status,
            "statusText": reason,
            "httpVersion": version,
            "cookies": [],
            "headers": _har_headers(response_headers),
            "content": {
                "size": plain_size,
                "mimeType": mime_type,
            },
            "redirectURL": response.getheader("location") or "",
            "headersSize": -1,
            "bodySize": len(raw),
            "_transferSize": len(raw),
        },
        "cache": {},
        "timings": {
            "blocked": 0,
            "dns": round(clock.dns or 0, 3),
            "connect": round(clock.connect or 0, 3),
            "ssl": round(clock.ssl or -1 if scheme == "https" else -1, 3),
            "send": round(clock.send or 0, 3),
            "wait": round(clock.wait or 0, 3),
            "receive": round(clock.receive or 0, 3),
        },
        "serverIPAddress": server_ip,
        "connection": str(port),
        "pageref": "page_0",
    }
    if mime_type.startswith("text/html"):
        return entry, plain, url
    return entry, None, url


def har_template() -> Dict[str, Any]:
    """返回一个空的 HAR 1.2 骨架（含 creator 信息）。"""
    from . import __version__

    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "harscope", "version": __version__},
            "browser": {"name": "harscope-recorder", "version": __version__},
            "pages": [],
            "entries": [],
            "comment": "由 HarScope 录制器生成 · 默认不保存响应体内容",
        }
    }


def record(url: str, options: Optional[RecordOptions] = None) -> Dict[str, Any]:
    """录制一个 URL 的加载过程，返回可直接 JSON 序列化的 HAR 结构。

    :param url: 起始 URL。
    :param options: 录制配置，缺省使用默认策略。
    :raises NetworkRecordError: 起始请求失败（后续资源失败会被降级跳过）。
    :returns: HAR 1.2 字典。
    """
    import json

    options = options or RecordOptions()
    har = har_template()
    log = har["log"]

    page_started = datetime.now(timezone.utc)
    wall_started = time.perf_counter()
    page_id = "page_0"

    entries: List[Dict[str, Any]] = []
    title = ""

    entry, html, final_url = _fetch_entry_with_redirects(entries, url, options)
    if html:
        mime = entry["response"]["content"].get("mimeType", "")
        if mime.startswith("text/html"):
            try:
                title = _extract_title(html)
            except Exception:  # pragma: no cover - 标题解析失败不影响主流程
                title = ""

    assets: List[str] = []
    if html and options.max_assets > 0:
        try:
            assets = _collect_assets(html, final_url, options)
        except Exception:  # pragma: no cover - HTML 解析失败降级
            assets = []

    if assets:
        _fetch_assets_parallel(entries, assets, options, referer=final_url)

    total_ms = (time.perf_counter() - wall_started) * 1000.0
    log["pages"].append(
        {
            "startedDateTime": _iso(page_started),
            "id": page_id,
            "title": title or final_url,
            "pageTimings": {
                "onContentLoad": round(total_ms * 0.7, 3),
                "onLoad": round(total_ms, 3),
            },
        }
    )
    log["entries"] = entries
    return har


def _fetch_entry_with_redirects(
    sink: List[Dict[str, Any]],
    url: str,
    options: RecordOptions,
    *,
    referer: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[bytes], str]:
    """跟随重定向地抓取一个 URL，把每一跳都写进 ``sink``。

    :returns: ``(最终跳 entry, HTML 字节（若最终是 HTML）, 最终 URL)``。
    """
    current = url
    last: Dict[str, Any] = {}
    html: Optional[bytes] = None
    hops = 0
    while True:
        entry, page_html, current_final = _fetch_once(current, options, referer=referer)
        sink.append(entry)
        last = entry
        html = page_html
        current = current_final
        location = entry["response"].get("redirectURL") or ""
        if (
            options.follow_redirects
            and location
            and 300 <= entry["response"]["status"] < 400
            and hops < max(0, options.max_redirects)
        ):
            target = urljoin(current, location)
            if options.same_host_only and (
                urlsplit(target).hostname or ""
            ) != (urlsplit(url).hostname or ""):
                break
            current = target
            hops += 1
            referer = current_final
            continue
        break
    return last, html, current


def _fetch_assets_parallel(
    sink: List[Dict[str, Any]],
    assets: Sequence[str],
    options: RecordOptions,
    *,
    referer: Optional[str] = None,
    max_workers: int = 6,
) -> None:
    """并发抓取子资源，更贴近浏览器行为。

    失败会被静默忽略（单个资源拿不到不影响整份 HAR 的可用性）。
    """
    from concurrent.futures import ThreadPoolExecutor

    def worker(url: str) -> Tuple[str, List[Dict[str, Any]]]:
        local: List[Dict[str, Any]] = []
        _fetch_entry_with_redirects(local, url, options, referer=referer)
        return url, local

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(assets)))) as pool:
        futures = [pool.submit(worker, url) for url in assets]
        for future in futures:
            try:
                _url, local_entries = future.result()
            except Exception:  # pragma: no cover - 单个资源失败忽略
                continue
            sink.extend(local_entries)


def _collect_assets(html: bytes, base_url: str, options: RecordOptions) -> List[str]:
    """抽取 HTML 中的一级资源 URL。

    :param html: 页面字节。
    :param base_url: 用于解析相对地址的基准 URL。
    :param options: 录制配置（决定是否限制同源）。
    """
    text = html.decode(_detect_charset(html), "replace")
    parser = _AssetCollector(base_url)
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # pragma: no cover - 畸形 HTML 直接放弃
        return []
    seen: Dict[str, None] = {}
    result: List[str] = []
    base_host = urlsplit(base_url).hostname or ""
    for candidate in parser.assets:
        if candidate in seen:
            continue
        seen[candidate] = None
        if options.same_host_only and (urlsplit(candidate).hostname or "") != base_host:
            continue
        result.append(candidate)
        if len(result) >= max(0, options.max_assets):
            break
    return result


def _detect_charset(html: bytes) -> str:
    """从 meta charset / XML 声明里猜一下编码，猜不到就用 utf-8。"""
    import re

    head = html[:2048].decode("ascii", "ignore")
    match = re.search(r'charset=["\']?([\w-]+)', head, re.IGNORECASE)
    return (match.group(1) if match else "utf-8") or "utf-8"


def _extract_title(html: bytes) -> str:
    """提取 ``<title>`` 文本。"""
    import re

    text = html.decode(_detect_charset(html), "replace")
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    import html as html_module

    value = re.sub(r"\s+", " ", match.group(1)).strip()
    return html_module.unescape(value)[:200]
