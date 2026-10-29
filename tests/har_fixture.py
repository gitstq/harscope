"""合成 HAR 夹具生成器。

为了让测试可复现、可离线运行，这里手工构造一个「足够脏」的 HAR：

* 一个 HTML 文档 + 多个静态资源 + 一次跳转 + 一个 API 调用；
* 刻意混入：``headersSize=-1``、缺 ``content``、缺 ``startedDateTime``、
  明文子资源（用于触发混合内容告警）、重复请求、带敏感 query 参数的请求；
* 时间轴分布刻意重叠，用来验证瀑布图并发计算。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

BASE_TIME = datetime(2026, 10, 30, 9, 0, 0, tzinfo=timezone(timedelta(hours=8)))


def _iso(offset_ms: float) -> str:
    """把相对毫秒偏移转成 HAR 时间字符串。"""
    moment = BASE_TIME + timedelta(milliseconds=offset_ms)
    return moment.isoformat(timespec="milliseconds")


def entry(
    *,
    url: str,
    method: str = "GET",
    status: int = 200,
    mime: str = "text/html",
    start: float = 0.0,
    timings: Dict[str, float] | None = None,
    body_size: int = 1024,
    content_size: int | None = None,
    headers_size: int = 320,
    include_content: bool = True,
    include_started: bool = True,
    response_headers: List[Dict[str, str]] | None = None,
    set_cookies: List[Dict[str, Any]] | None = None,
    cache: Dict[str, Any] | None = None,
    pageref: str = "page_0",
    resource_type: str | None = None,
    redirect_url: str = "",
    no_timings: bool = False,
    query: List[Dict[str, str]] | None = None,
    include_transfer_size: bool = True,
) -> Dict[str, Any]:
    """构造一条 HAR entry，字段尽量贴近真实采集器输出。"""
    duration = timings or {
        "blocked": round(0.5 + body_size % 7 * 0.3, 2),
        "dns": round(1.0 + start % 5, 2),
        "connect": round(4.0 + (start % 11), 2),
        "ssl": round(18.0 + start % 9, 2),
        "send": 0.6,
        "wait": round(12.0 + body_size / 5120.0 + start / 12.0, 2),
        "receive": round(2.0 + body_size / 20480.0, 2),
    }
    if no_timings:
        duration = {}
        total = 42.0
    else:
        total = float(sum(duration.values()))
    headers = response_headers if response_headers is not None else None
    response: Dict[str, Any] = {
        "status": status,
        "statusText": "OK" if status < 400 else "Error",
        "httpVersion": "http/2.0",
        "headers": headers if headers is not None else [
            {"name": "content-type", "value": mime},
        ],
        "cookies": set_cookies or [],
        "headersSize": headers_size,
        "bodySize": body_size,
        "redirectURL": redirect_url,
    }
    if include_transfer_size:
        response["_transferSize"] = body_size
    if include_content:
        response["content"] = {
            "size": content_size if content_size is not None else body_size * 2,
            "mimeType": mime,
        }
    item: Dict[str, Any] = {
        "request": {
            "method": method,
            "url": url,
            "httpVersion": "http/2.0",
            "headers": [
                {"name": "user-agent", "value": "HarScope-Test/1.0"},
                {"name": "accept", "value": "*/*"},
            ],
            "cookies": [],
            "queryString": query or [],
            "headersSize": 180,
            "bodySize": 0,
        },
        "response": response,
        "cache": cache or {},
        "pageref": pageref,
        "serverIPAddress": "93.184.216.34",
        "connection": "443",
    }
    if include_started:
        item["startedDateTime"] = _iso(start)
    if not no_timings:
        item["timings"] = dict(duration)
    if resource_type:
        item["_resourceType"] = resource_type
    item["time"] = total
    return item


def build_sample_har() -> Dict[str, Any]:
    """构造一份完整的样本 HAR。"""
    secure_doc_headers = [
        {"name": "content-type", "value": "text/html; charset=utf-8"},
        {"name": "strict-transport-security", "value": "max-age=31536000; includeSubDomains"},
        {"name": "content-security-policy", "value": "default-src 'self'"},
        {"name": "cache-control", "value": "no-cache"},
    ]
    asset_headers = [
        {"name": "content-type", "value": "application/javascript"},
        {"name": "cache-control", "value": "public, max-age=31536000, immutable"},
        {"name": "content-encoding", "value": "gzip"},
    ]

    entries: List[Dict[str, Any]] = [
        entry(
            url="https://shop.example.com/",
            start=0,
            body_size=18432,
            content_size=57344,
            headers_size=612,
            response_headers=secure_doc_headers,
            resource_type="document",
        ),
        entry(
            url="https://cdn.example.com/assets/app.4f2a.js",
            start=58,
            mime="application/javascript",
            body_size=92160,
            content_size=245760,
            headers_size=240,
            response_headers=asset_headers,
            resource_type="script",
        ),
        entry(
            url="https://cdn.example.com/assets/app.4f2a.js",
            start=190,
            mime="application/javascript",
            body_size=64,
            content_size=245760,
            headers_size=180,
            response_headers=[
                {"name": "content-type", "value": "application/javascript"},
                {"name": "age", "value": "12"},
            ],
            resource_type="script",
            cache={"beforeRequest": {"hitCount": 3, "lastAccess": "2026-10-30T08:00:00+08:00"}},
        ),
        entry(
            url="https://cdn.example.com/assets/theme.css",
            start=61,
            mime="text/css",
            body_size=32768,
            content_size=131072,
            headers_size=210,
            response_headers=asset_headers,
            resource_type="stylesheet",
        ),
        entry(
            url="https://cdn.example.com/assets/hero.webp",
            start=64,
            mime="image/webp",
            body_size=245760,
            content_size=245760,
            headers_size=160,
            response_headers=[
                {"name": "content-type", "value": "image/webp"},
                {"name": "cache-control", "value": "max-age=604800"},
            ],
            resource_type="image",
        ),
        entry(
            url="https://shop.example.com/legacy/track.js",
            start=70,
            mime="application/javascript",
            body_size=5120,
            content_size=5120,
            headers_size=-1,
            include_content=False,
            include_transfer_size=False,
            resource_type="script",
        ),
        entry(
            url="http://thirdparty.example.com/beacon.gif",
            start=88,
            mime="image/gif",
            body_size=43,
            content_size=43,
            headers_size=-1,
            resource_type="image",
        ),
        entry(
            url="https://api.example.com/v1/cart",
            start=120,
            mime="application/json",
            body_size=4096,
            content_size=8192,
            headers_size=300,
            response_headers=[
                {"name": "content-type", "value": "application/json"},
                {"name": "x-powered-by", "value": "Express 4.18.2"},
                {"name": "server", "value": "nginx/1.24.0"},
                {"name": "set-cookie", "value": "cart_id=abc123; Path=/"},
            ],
            set_cookies=[{"name": "cart_id", "value": "abc123", "secure": False,
                          "httpOnly": False}],
            resource_type="xhr",
        ),
        entry(
            url="https://api.example.com/v1/checkout",
            method="POST",
            status=500,
            mime="application/json",
            start=210,
            body_size=256,
            content_size=512,
            headers_size=280,
            resource_type="xhr",
        ),
        entry(
            url="https://shop.example.com/old-path",
            status=301,
            start=0,
            body_size=0,
            content_size=0,
            headers_size=140,
            response_headers=[
                {"name": "location", "value": "/"},
            ],
            redirect_url="https://shop.example.com/",
            resource_type="document",
        ),
        entry(
            url="https://files.example.com/download?token=secret123&file=report.pdf",
            start=260,
            mime="application/pdf",
            body_size=1048576,
            content_size=1048576,
            headers_size=220,
            query=[
                {"name": "token", "value": "secret123"},
                {"name": "file", "value": "report.pdf"},
            ],
            resource_type="other",
        ),
        entry(
            url="https://cdn.example.com/assets/missing.svg",
            status=404,
            start=300,
            mime="",
            body_size=0,
            content_size=0,
            headers_size=120,
            resource_type="image",
        ),
        entry(
            url="https://cdn.example.com/assets/legacy/no-timings.css",
            start=320,
            mime="text/css",
            body_size=2048,
            content_size=2048,
            no_timings=True,
            resource_type="stylesheet",
        ),
        entry(
            url="https://cdn.example.com/assets/no-started.js",
            mime="application/javascript",
            body_size=3072,
            content_size=3072,
            include_started=False,
            resource_type="script",
        ),
    ]

    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "HarScope Fixture", "version": "1.0"},
            "browser": {"name": "Chrome", "version": "134.0.0.0"},
            "pages": [
                {
                    "startedDateTime": _iso(0),
                    "id": "page_0",
                    "title": "示例商城 · 首页",
                    "pageTimings": {"onContentLoad": 320.5, "onLoad": 640.0},
                }
            ],
            "entries": entries,
            "comment": "由 HarScope 测试夹具生成",
        }
    }


def sample_json() -> str:
    """样本 HAR 的 JSON 文本。"""
    return json.dumps(build_sample_har(), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print(sample_json())
