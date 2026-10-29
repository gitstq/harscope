"""传输安全与响应头合规审计。

审计完全离线进行：只用 HAR 里已经记录下来的请求/响应元数据做静态判定，
不发起任何外部请求，因此在 CI、内网、离线环境里都能跑。

每项检查都会产出 :class:`Finding`（含等级、证据 URL），并由
:func:`audit` 汇总成 0~100 的 :class:`SecurityAudit.score`。
扣分权重刻意保守——宁可给出告警，也不假装安全。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .model import Har, HarEntry, HarResponse

__all__ = [
    "Finding",
    "SecurityAudit",
    "audit",
    "SECURITY_HEADERS",
    "SENSITIVE_QUERY_KEYS",
]

#: 建议在 HTML 文档响应上出现的安全响应头（值用于 README/报告展示）。
SECURITY_HEADERS: Tuple[Tuple[str, str], ...] = (
    ("strict-transport-security", "HSTS：强制 HTTPS，抵御降级攻击"),
    ("content-security-policy", "CSP：限制资源加载来源，缓解 XSS"),
    ("x-content-type-options", "nosniff：阻止 MIME 嗅探"),
    ("x-frame-options", "XFO / frame-ancestors：防御点击劫持"),
    ("referrer-policy", "Referrer-Policy：控制来源信息泄漏"),
    ("permissions-policy", "Permissions-Policy：收敛浏览器敏感能力"),
    ("cross-origin-opener-policy", "COOP：隔离跨源窗口引用"),
)

#: 被认为不应出现在 URL query 中的敏感键名（小写匹配）。
SENSITIVE_QUERY_KEYS: Tuple[str, ...] = (
    "token",
    "access_token",
    "access-token",
    "id_token",
    "refresh_token",
    "api_key",
    "apikey",
    "key",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "pwd",
    "session",
    "sessionid",
    "session_id",
    "auth",
    "authorization",
    "private_key",
    "signature",
    "sig",
    "ticket",
    "code",
)

#: 会被计入评分的「关键三件套」响应头。
CRITICAL_HEADERS: Tuple[str, ...] = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
)

#: 会泄漏后端实现细节的响应头。
DISCLOSURE_HEADERS: Tuple[str, ...] = (
    "x-powered-by",
    "server",
    "x-aspnet-version",
    "x-aspnetmvc-version",
    "x-generator",
    "x-drupal-cache",
    "x-runtime",
)

#: 只对「HTML/JSON/文本」类响应要求安全头；静态资源不苛求。
POLICY_MIME_PREFIXES: Tuple[str, ...] = (
    "text/html",
    "application/xhtml",
    "application/json",
    "text/plain",
)


@dataclass
class Finding:
    """一条安全/合规发现。"""

    severity: str  # high | medium | low | info
    category: str
    message: str
    url: str = ""
    hint: str = ""

    @property
    def severity_label(self) -> str:
        """本地化等级标签（中文），用于终端与报告输出。"""
        return {
            "high": "高危",
            "medium": "中危",
            "low": "低危",
            "info": "提示",
        }.get(self.severity, self.severity)


@dataclass
class SecurityAudit:
    """一次完整的安全审计结果。"""

    findings: List[Finding] = field(default_factory=list)
    checked_requests: int = 0
    https_requests: int = 0
    http_requests: int = 0
    missing_header_counts: Dict[str, int] = field(default_factory=dict)
    documents_checked: int = 0

    @property
    def high_count(self) -> int:
        """高危发现数量。"""
        return sum(1 for f in self.findings if f.severity == "high")

    @property
    def medium_count(self) -> int:
        """中危发现数量。"""
        return sum(1 for f in self.findings if f.severity == "medium")

    @property
    def low_count(self) -> int:
        """低危发现数量。"""
        return sum(1 for f in self.findings if f.severity == "low")

    @property
    def info_count(self) -> int:
        """提示类发现数量。"""
        return sum(1 for f in self.findings if f.severity == "info")

    @property
    def https_ratio(self) -> float:
        """HTTPS 请求占比（0~1）。"""
        total = self.https_requests + self.http_requests
        return (self.https_requests / total) if total else 1.0

    @property
    def score(self) -> int:
        """综合安全评分（0~100）。

        采用**分量加权**而非单纯扣分，避免少量文件就能把分数打到 0：

        ``传输层``   30 分 × HTTPS 请求占比
        ``基线响应头`` 30 分 × 关键响应头（HSTS / CSP / nosniff）覆盖率
        ``发现密度``  40 分 × ``1 − 加权发现密度 / 30``，权重 high=3、medium=1.2、low=0.4

        这样在同一份抓包中增加请求数不会机械地拉低分数，而真正危险的
        问题（明文传输、凭据入 URL）依然会把分数直接压到及格线以下。
        """
        transport = 30.0 * min(max(self.https_ratio, 0.0), 1.0)

        denominator = len(CRITICAL_HEADERS) * max(self.documents_checked, 1)
        missing = sum(
            count for header, count in self.missing_header_counts.items()
            if header in CRITICAL_HEADERS
        )
        header_coverage = 1.0 if not self.documents_checked else min(
            missing / denominator, 1.0
        )
        headers = 30.0 * (1.0 - header_coverage)

        pressure = self.high_count * 3.0 + self.medium_count * 1.2 + self.low_count * 0.4
        findings_component = 40.0 * max(0.0, 1.0 - pressure / 30.0)
        return int(round(transport + headers + findings_component))

    @property
    def grade(self) -> str:
        """评分区间对应的等级字母。"""
        score = self.score
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "E"

    def by_severity(self, severity: str) -> List[Finding]:
        """按等级过滤发现列表。"""
        return [f for f in self.findings if f.severity == severity]

    def to_dict(self) -> Dict[str, object]:
        """转成可 JSON 序列化的字典。"""
        return {
            "score": self.score,
            "grade": self.grade,
            "checked_requests": self.checked_requests,
            "https_requests": self.https_requests,
            "http_requests": self.http_requests,
            "missing_header_counts": dict(self.missing_header_counts),
            "counts": {
                "high": self.high_count,
                "medium": self.medium_count,
                "low": self.low_count,
                "info": self.info_count,
            },
            "findings": [
                {
                    "severity": f.severity,
                    "severity_label": f.severity_label,
                    "category": f.category,
                    "message": f.message,
                    "url": f.url,
                    "hint": f.hint,
                }
                for f in self.findings
            ],
        }


def audit(har: Har) -> SecurityAudit:
    """对一个 HAR 会话执行全套安全与合规检查。

    :param har: 已解析的 HAR 会话。
    :returns: :class:`SecurityAudit` 结果对象。
    """
    audit_result = SecurityAudit(checked_requests=len(har.entries))
    seen_documents: Set[str] = set()

    https_hosts: Set[str] = set()
    http_entries: List[HarEntry] = []

    for entry in har.entries:
        if entry.is_secure:
            audit_result.https_requests += 1
            https_hosts.add(entry.host)
        else:
            audit_result.http_requests += 1
            http_entries.append(entry)

    # ① 明文传输
    for entry in http_entries[:5]:
        audit_result.findings.append(
            Finding(
                severity="high" if entry.request.has_request_body else "medium",
                category="明文传输",
                message="请求通过未加密的 HTTP 发起：%s" % entry.request.method,
                url=entry.url,
                hint="全站启用 HTTPS 并配置 301 跳转 + HSTS。",
            )
        )
    if len(http_entries) > 5:
        audit_result.findings.append(
            Finding(
                severity="medium",
                category="明文传输",
                message="另有 %d 条明文 HTTP 请求未逐条列出" % (len(http_entries) - 5),
                hint="升级资源引用为 https:// 或使用协议相对 URL。",
            )
        )

    # ② 混合内容：站点主体是 HTTPS，却引用了明文子资源
    if https_hosts:
        for entry in http_entries:
            if entry.host in https_hosts or _looks_subresource(entry):
                audit_result.findings.append(
                    Finding(
                        severity="high",
                        category="混合内容",
                        message="HTTPS 页面中引用了明文子资源：%s" % entry.request.display_path,
                        url=entry.url,
                        hint="浏览器会拦截或降级该资源，需改用 HTTPS。",
                    )
                )
                break

    # ③ 逐个响应检查
    for entry in har.entries:
        response = entry.response
        if not response.status:
            continue
        if _is_policy_document(response):
            audit_result.documents_checked += 1
            seen_documents.add(entry.request.base_url)
            _check_security_headers(entry, response, audit_result)
        _check_disclosure(entry, response, audit_result)
        _check_cookies(entry, response, audit_result)
        _check_cache_headers(entry, response, audit_result)
        _check_sensitive_url(entry, audit_result)

    # ④ 交叉重复项去重，避免报告被同一 URL 淹没
    audit_result.findings = _dedupe(audit_result.findings, per=2)
    return audit_result


def _looks_subresource(entry: HarEntry) -> bool:
    """根据 MIME / 资源类型猜测该请求是否为页面引用的子资源。"""
    mime = (entry.response.mime_type or "").lower()
    if mime.startswith(("image/", "font/", "audio/", "video/")):
        return True
    if "javascript" in mime or "css" in mime:
        return True
    return (entry.resource_type or "") in {"script", "stylesheet", "image", "font", "media"}


def _is_policy_document(response: HarResponse) -> bool:
    """是否属于应当强校验安全头的「文档类」响应。"""
    mime = (response.mime_type or "").lower()
    if not mime:
        # 无 MIME 时按状态码兜底：只有 2xx 且带内容才算文档
        return 200 <= response.status < 300
    return any(mime.startswith(prefix) for prefix in POLICY_MIME_PREFIXES)


def _check_security_headers(
    entry: HarEntry, response: HarResponse, audit_result: SecurityAudit
) -> None:
    """检查缺失的安全响应头，缺失数量去重后合并统计。"""
    missing: List[Tuple[str, str]] = []
    for header, reason in SECURITY_HEADERS:
        value = response.header(header)
        if value is None or not value.strip():
            missing.append((header, reason))
    for header, reason in missing:
        audit_result.missing_header_counts[header] = (
            audit_result.missing_header_counts.get(header, 0) + 1
        )
        severity = "medium" if header in {
            "strict-transport-security",
            "content-security-policy",
            "x-content-type-options",
        } else "low"
        audit_result.findings.append(
            Finding(
                severity=severity,
                category="响应头缺失",
                message="缺少 %s —— %s" % (header, reason),
                url=entry.url,
                hint="在网关或应用层统一注入安全响应头。",
            )
        )


def _check_disclosure(
    entry: HarEntry, response: HarResponse, audit_result: SecurityAudit
) -> None:
    """检查是否泄漏后端版本信息。"""
    for header in DISCLOSURE_HEADERS:
        value = response.header(header)
        if value and _contains_version(value):
            audit_result.findings.append(
                Finding(
                    severity="low",
                    category="信息泄漏",
                    message="响应头 %s 暴露了版本号：%s" % (header, value),
                    url=entry.url,
                    hint="在反向代理层移除或统一改写该响应头。",
                )
            )


def _contains_version(value: str) -> bool:
    """粗糙但有效地判断是否包含版本号片段。"""
    import re

    return bool(re.search(r"\d", value)) and bool(re.search(r"[\d]+\.[\w.]+", value))


def _check_cookies(
    entry: HarEntry, response: HarResponse, audit_result: SecurityAudit
) -> None:
    """检查 Set-Cookie 的安全属性是否完整。"""
    for cookie in response.cookies:
        problems: List[str] = []
        if entry.is_secure and not cookie.secure:
            problems.append("缺少 Secure")
        if not cookie.http_only:
            problems.append("缺少 HttpOnly")
        if not cookie.same_site:
            problems.append("缺少 SameSite")
        if not problems:
            continue
        audit_result.findings.append(
            Finding(
                severity="medium" if "缺少 Secure" in problems else "low",
                category="Cookie 属性",
                message="Cookie %s %s" % (cookie.name, "、".join(problems)),
                url=entry.url,
                hint="建议 Secure; HttpOnly; SameSite=Lax 组合，敏感会话用 Strict。",
            )
        )


def _check_cache_headers(
    entry: HarEntry, response: HarResponse, audit_result: SecurityAudit
) -> None:
    """检查动态文档是否缺失缓存控制。"""
    if not _is_policy_document(response):
        return
    cache_control = (response.header("cache-control") or "").lower()
    pragma = (response.header("pragma") or "").lower()
    expires = response.header("expires")
    if not cache_control and not pragma and not expires:
        audit_result.findings.append(
            Finding(
                severity="info",
                category="缓存策略",
                message="文档响应未提供任何 Cache-Control 指令，浏览器行为不可控",
                url=entry.url,
                hint="静态文档用 immutable/max-age，动态文档显式 no-store。",
            )
        )


def _check_sensitive_url(entry: HarEntry, audit_result: SecurityAudit) -> None:
    """检查 URL query 中是否携带敏感参数名。"""
    hits = [
        name
        for name, _value in entry.request.query_string
        if name.lower() in SENSITIVE_QUERY_KEYS
    ]
    if not hits:
        return
    audit_result.findings.append(
        Finding(
            severity="high",
            category="凭据泄漏",
            message="URL 参数可能包含凭据类字段：%s" % "、".join(sorted(set(hits))),
            url=_mask(entry.url),
            hint="凭据应放在 Authorization 头或 POST body 中；URL 会被日志、Referer 记录。",
        )
    )


def _mask(url: str) -> str:
    """对 URL 中的参数值做脱敏，避免审计报告二次泄漏。"""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = [(k, "***") for k, _v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), ""))


def _dedupe(findings: Sequence[Finding], per: int = 2) -> List[Finding]:
    """同一「类别 + 消息」最多保留 ``per`` 条，其余折叠为汇总行。"""
    counts: Dict[Tuple[str, str], int] = {}
    kept: List[Finding] = []
    for item in findings:
        key = (item.category, item.message)
        counts[key] = counts.get(key, 0) + 1
        if counts[key] <= per:
            kept.append(item)
    overflow: Dict[str, int] = {}
    for item in findings:
        key = (item.category, item.message)
        if counts[key] > per:
            overflow[item.category] = overflow.get(item.category, 0) + counts[key] - per
    for entry_category, total in overflow.items():
        # 每个类别只补一条汇总，避免指数膨胀
        buckets = {k for k in counts if k[0] == entry_category}
        if buckets:
            kept.append(
                Finding(
                    severity="info",
                    category=entry_category,
                    message="另有 %d 条同类发现已折叠，详见 JSON 导出" % total,
                    hint="使用 `harscope export security --format json` 查看完整清单。",
                )
            )
    return kept
