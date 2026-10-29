"""导出层：JSON / CSV / Markdown / SVG 瀑布图 / 自包含 HTML 报告。

所有导出都不依赖 Jinja2、matplotlib 等第三方库：

* SVG 由字符串模板手绘，可直接在浏览器、Confluence、VS Code 预览中打开；
* HTML 报告内联了 SVG 与全部样式，**单文件离线可用**，适合作为 CI 产物归档；
* CSV 使用 :mod:`csv` 并写 ``utf-8-sig`` BOM，Excel 双击不会乱码。
"""

from __future__ import annotations

import csv
import html
import io
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from .analyze import PHASE_COLORS, PHASE_LABELS, HarAnalysis
from .exceptions import ExportError
from .model import HarEntry
from .render import human_bytes, human_ms, human_count
from .security import SecurityAudit

__all__ = [
    "to_entry_rows",
    "to_json",
    "to_csv",
    "to_markdown",
    "to_svg_waterfall",
    "to_html_report",
    "write_export",
]

#: 支持的导出格式与其默认扩展名。
FORMATS: Dict[str, str] = {
    "json": "json",
    "csv": "csv",
    "md": "md",
    "markdown": "md",
    "svg": "svg",
    "html": "html",
}


def _esc(value: Any) -> str:
    """HTML/XML 转义。"""
    return html.escape(str(value), quote=True)


# --------------------------------------------------------------------------
# JSON / CSV
# --------------------------------------------------------------------------
def to_entry_rows(entries: Iterable[HarEntry]) -> List[List[Any]]:
    """把若干条 HAR 记录摊平成表格行。

    :returns: 首行为表头，其后为数据行。
    """
    header = [
        "#",
        "method",
        "url",
        "host",
        "status",
        "mime",
        "total_ms",
        "wait_ms",
        "size_bytes",
        "body_bytes",
        "transfer_bytes",
        "started",
        "secure",
        "cache_hit",
    ]
    rows: List[List[Any]] = [header]
    for entry in entries:
        rows.append([
            entry.index,
            entry.request.method,
            entry.url,
            entry.host,
            entry.response.status,
            entry.response.mime_type,
            round(entry.time_ms, 2),
            round(entry.wait_ms, 2),
            entry.total_size,
            entry.response.body_transfer_size,
            entry.response.transfer_size
            if entry.response.transfer_size is not None
            else entry.response.body_size,
            entry.started_date_time.isoformat() if entry.started_date_time else "",
            entry.is_secure,
            entry.is_cache_hit,
        ])
    return rows


def to_json(analysis: HarAnalysis, *, audit: Optional[SecurityAudit] = None,
            include_entries: bool = False) -> str:
    """导出完整分析结果 JSON。

    :param analysis: 分析结果。
    :param audit: 可选的安全审计结果。
    :param include_entries: 是否附带逐条请求的明细。
    """
    payload: Dict[str, Any] = {
        "tool": "harscope",
        "summary": analysis.summary_dict(),
        "status_classes": analysis.status_classes,
        "domains": [
            {
                "host": stat.host,
                "requests": stat.requests,
                "transfer_bytes": stat.transfer_bytes,
                "header_bytes": stat.header_bytes,
                "avg_ms": round(stat.avg_ms, 2),
                "wait_ms": round(stat.wait_ms, 2),
                "errors": stat.errors,
                "secure": stat.secure,
            }
            for stat in analysis.domain_stats(top=1000)
        ],
        "mime": [
            {
                "mime_type": stat.mime_type,
                "requests": stat.requests,
                "transfer_bytes": stat.transfer_bytes,
                "uncompressed_bytes": stat.uncompressed_bytes,
                "saving_bytes": stat.saving_bytes,
            }
            for stat in analysis.mime_stats(top=1000)
        ],
        "slowest": [
            {
                "url": entry.url,
                "method": entry.request.method,
                "total_ms": round(entry.time_ms, 2),
                "wait_ms": round(entry.wait_ms, 2),
                "transfer_bytes": entry.total_size,
            }
            for entry in analysis.slowest(20)
        ],
        "largest": [
            {
                "url": entry.url,
                "transfer_bytes": entry.total_size,
                "uncompressed_bytes": entry.response.uncompressed_body_size,
            }
            for entry in analysis.largest(20)
        ],
        "duplicates": [
            {
                "method": group.method,
                "url": group.url,
                "count": group.count,
                "transfer_bytes": group.transfer_bytes,
                "wasted_bytes": group.wasted_bytes,
            }
            for group in analysis.duplicates(top=1000)
        ],
        "pages": [
            {
                "page_id": page.page_id,
                "title": page.title,
                "requests": page.requests,
                "transfer_bytes": page.transfer_bytes,
                "duration_ms": round(page.duration_ms, 2),
                "on_load_ms": page.on_load_ms,
            }
            for page in analysis.page_stats()
        ],
    }
    if audit is not None:
        payload["security"] = audit.to_dict()
    if include_entries:
        from itertools import islice

        rows = to_entry_rows(analysis.entries)
        header, *body = rows
        payload["entries"] = [dict(zip(header, row)) for row in islice(body, 0, 5000)]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def to_csv(entries: Iterable[HarEntry]) -> str:
    """导出逐条请求的 CSV（带 BOM，Excel 友好）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    rows = to_entry_rows(entries)
    writer.writerow(rows[0])
    writer.writerows(rows[1:])
    # utf-8-sig 的 BOM 让 Excel 正确识别 UTF-8；以字符串形式返回时手动补上
    return "﻿" + buffer.getvalue()


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------
def to_markdown(analysis: HarAnalysis, *, audit: Optional[SecurityAudit] = None) -> str:
    """导出人类可读的 Markdown 速览报告。"""
    lines: List[str] = []
    summary = analysis.summary_dict()
    lines.append("# HarScope 分析报告")
    lines.append("")
    lines.append("> 来源：`%s` ｜ 标题：%s ｜ HAR 版本：%s" % (
        _esc(summary["source"]), _esc(summary["title"]), _esc(summary["har_version"]),
    ))
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("| --- | --- |")
    pairs = [
        ("请求总数", human_count(analysis.total_requests)),
        ("涉及域名", human_count(analysis.unique_hosts)),
        ("会话跨度", human_ms(analysis.duration_ms)),
        ("累计请求耗时", human_ms(analysis.total_time_ms)),
        ("并发度估计", "%.2f×" % analysis.parallelism),
        ("总传输体积", human_bytes(analysis.transfer_bytes)),
        ("其中响应体", human_bytes(analysis.body_transfer_bytes)),
        ("其中头部", human_bytes(analysis.header_bytes) + "（%.1f%%）" % (analysis.header_ratio * 100)),
        ("解压后响应体", human_bytes(analysis.uncompressed_body_bytes)),
        ("压缩节省", "%s（%.1f%%）" % (
            human_bytes(analysis.compression_saving_bytes),
            analysis.compression_saving_ratio * 100,
        )),
        ("HTTPS 占比", "%.1f%%" % (analysis.https_ratio * 100)),
        ("缓存命中率", "%.1f%%" % (analysis.cache_hit_ratio * 100)),
        ("平均耗时", human_ms(analysis.average_ms)),
        ("P50 / P95", "%s / %s" % (human_ms(analysis.p50_ms), human_ms(analysis.p95_ms))),
        ("平均 TTFB", human_ms(analysis.average_wait_ms)),
    ]
    for name, value in pairs:
        lines.append("| %s | %s |" % (name, value))
    lines.append("")

    lines.append("## 状态码分布")
    lines.append("")
    lines.append("| 类别 | 数量 | 占比 |")
    lines.append("| --- | --- | --- |")
    for key in sorted(analysis.status_classes):
        count = analysis.status_classes[key]
        lines.append("| %s | %s | %.1f%% |" % (
            key, human_count(count), count / max(analysis.total_requests, 1) * 100,
        ))
    lines.append("")

    lines.append("## 域名分布 TOP10")
    lines.append("")
    lines.append("| 域名 | 请求数 | 传输体积 | 占比 | 平均耗时 | 错误 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for stat in analysis.domain_stats(10):
        lines.append("| `%s` | %s | %s | %.1f%% | %s | %d |" % (
            _esc(stat.host), human_count(stat.requests), human_bytes(stat.transfer_bytes),
            stat.transfer_ratio * 100, human_ms(stat.avg_ms), stat.errors,
        ))
    lines.append("")

    lines.append("## 最慢的 10 个请求")
    lines.append("")
    lines.append("| # | 方法 | URL | 耗时 | TTFB | 体积 |")
    lines.append("| ---: | --- | --- | ---: | ---: | ---: |")
    for entry in analysis.slowest(10):
        lines.append("| %d | %s | `%s` | %s | %s | %s |" % (
            entry.index, entry.request.method, _esc(entry.request.display_path),
            human_ms(entry.time_ms), human_ms(entry.wait_ms), human_bytes(entry.total_size),
        ))
    lines.append("")

    dupes = analysis.duplicates(top=10)
    if dupes:
        lines.append("## 重复请求")
        lines.append("")
        lines.append("| 方法 | URL | 重复次数 | 冗余体积 |")
        lines.append("| --- | --- | ---: | ---: |")
        for group in dupes:
            lines.append("| %s | `%s` | %d | %s |" % (
                group.method, _esc(group.url[:80]), group.count, human_bytes(group.wasted_bytes),
            ))
        lines.append("")

    if audit is not None:
        lines.append("## 安全审计")
        lines.append("")
        lines.append("评分 **%d / 100（%s 级）** ｜ 高危 %d ｜ 中危 %d ｜ 低危 %d" % (
            audit.score, audit.grade, audit.high_count, audit.medium_count, audit.low_count,
        ))
        lines.append("")
        lines.append("| 等级 | 类别 | 说明 | 证据 |")
        lines.append("| --- | --- | --- | --- |")
        for finding in audit.findings[:25]:
            lines.append("| %s | %s | %s | `%s` |" % (
                finding.severity_label, finding.category,
                _esc(finding.message), _esc(finding.url[:70]),
            ))
        lines.append("")

    if analysis.notes:
        lines.append("## 数据质量提示")
        lines.append("")
        for note in analysis.notes:
            lines.append("- %s" % note)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("由 [HarScope](https://github.com/gitstq/harscope) 导出 · 零依赖 HAR 分析工作台")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# SVG 瀑布图
# --------------------------------------------------------------------------
def to_svg_waterfall(analysis: HarAnalysis, *, limit: int = 40) -> str:
    """生成独立的 SVG 瀑布图文件。

    :param analysis: 分析结果。
    :param limit: 最多绘制多少行。
    """
    rows = analysis.waterfall(limit=limit)
    if not rows:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="120"><text x="12" y="40" font-size="14" fill="#555">没有可用的瀑布图数据</text></svg>'

    row_height = 22
    label_width = 330
    right_pad = 90
    left_pad = 12
    top_pad = 34
    total_ms = max(row.end_ms for row in rows) or 1.0
    plot_width = 900
    height = top_pad + len(rows) * row_height + 46
    width = left_pad + label_width + plot_width + right_pad
    scale = plot_width / total_ms

    parts: List[str] = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">'
        % (width, height, width, height)
    )
    parts.append(
        '<rect width="100%%" height="100%%" fill="#ffffff"/>'
        '<text x="%d" y="22" font-size="15" fill="#111827">HarScope 瀑布图 · %d 条请求 · 总跨度 %s</text>'
        % (left_pad, len(rows), human_ms(total_ms))
    )

    # 时间刻度：以人类友好的步长生成网格线
    step = _nice_step(total_ms)
    tick = 0.0
    while tick <= total_ms:
        x = left_pad + label_width + tick * scale
        parts.append(
            '<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#e5e7eb" stroke-width="1"/>'
            % (x, top_pad - 8, x, height - 34)
        )
        parts.append(
            '<text x="%.1f" y="%d" font-size="10" fill="#9ca3af" text-anchor="middle">%s</text>'
            % (x, top_pad - 12, human_ms(tick))
        )
        tick += step

    for row_index, row in enumerate(rows):
        y = top_pad + row_index * row_height
        if row_index % 2 == 1:
            parts.append(
                '<rect x="%d" y="%d" width="%d" height="%d" fill="#f9fafb"/>'
                % (left_pad, y, width - left_pad - right_pad + 60, row_height)
            )
        label = "%s %s" % (row.entry.request.method, row.entry.request.display_path)
        parts.append(
            '<text x="%d" y="%d" font-size="11" fill="#374151">%s</text>'
            % (left_pad + 4, y + 15, _esc(_ellipsis(label, 46)))
        )
        cursor = 0.0
        for phase, value in row.phases:
            if value <= 0:
                continue
            x = left_pad + label_width + (row.offset_ms + cursor) * scale
            segment = max(0.6, value * scale)
            color = PHASE_COLORS.get(phase, "#9ca3af")
            parts.append(
                '<rect x="%.1f" y="%d" width="%.1f" height="12" rx="2" fill="%s">'
                '<title>%s %s</title></rect>'
                % (x, y + 3, segment, color, _esc(PHASE_LABELS.get(phase, phase)), human_ms(value))
            )
            cursor += value
        duration_label = "%s" % human_ms(row.duration_ms)
        parts.append(
            '<text x="%.1f" y="%d" font-size="10" fill="#6b7280">%s</text>'
            % (left_pad + label_width + plot_width + 6, y + 14, duration_label)
        )

    legend_y = height - 14
    cursor_x = left_pad
    for phase in ("blocked", "dns", "connect", "ssl", "send", "wait", "receive"):
        color = PHASE_COLORS.get(phase, "#9ca3af")
        parts.append(
            '<rect x="%d" y="%d" width="10" height="10" rx="2" fill="%s"/>'
            % (cursor_x, legend_y - 10, color)
        )
        parts.append(
            '<text x="%d" y="%d" font-size="10" fill="#6b7280">%s</text>'
            % (cursor_x + 14, legend_y, _esc(PHASE_LABELS.get(phase, phase)))
        )
        cursor_x += 14 + len(PHASE_LABELS.get(phase, phase)) * 11 + 10
    parts.append("</svg>")
    return "\n".join(parts)


def _ellipsis(text: str, limit: int) -> str:
    """简单的字符级省略（不区分宽字符，SVG 里够用即可）。"""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _nice_step(total_ms: float) -> float:
    """为时间轴挑选一个「好看」的刻度步长。"""
    candidates = (50, 100, 200, 250, 500, 1000, 2000, 5000, 10000, 30000, 60000)
    for candidate in candidates:
        if total_ms / candidate <= 12:
            return float(candidate)
    return 120000.0


# --------------------------------------------------------------------------
# HTML 报告
# --------------------------------------------------------------------------
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HarScope 报告 · {title}</title>
<style>
  :root {{ --fg:#111827; --muted:#6b7280; --line:#e5e7eb; --bg:#ffffff; --panel:#f9fafb; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:32px; background:var(--bg); color:var(--fg);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
         line-height:1.6; }}
  h1 {{ font-size:24px; margin:0 0 4px; }}
  h2 {{ font-size:18px; margin:32px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--line); }}
  .meta {{ color:var(--muted); font-size:13px; margin-bottom:24px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .card .k {{ font-size:12px; color:var(--muted); }}
  .card .v {{ font-size:20px; font-weight:650; margin-top:2px; }}
  .card .s {{ font-size:12px; color:var(--muted); }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; margin-top:8px; }}
  th,td {{ padding:7px 10px; border-bottom:1px solid var(--line); text-align:left; }}
  th {{ background:var(--panel); font-weight:600; }}
  td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .tag {{ display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; }}
  .high {{ background:#fee2e2; color:#b91c1c; }}
  .medium {{ background:#fef3c7; color:#b45309; }}
  .low {{ background:#e0f2fe; color:#0369a1; }}
  .info {{ background:#e5e7eb; color:#4b5563; }}
  .score {{ font-size:40px; font-weight:700; }}
  .grade {{ font-size:22px; color:var(--muted); }}
  .wrap {{ overflow-x:auto; }}
  footer {{ margin-top:36px; color:var(--muted); font-size:12px; }}
  code {{ background:var(--panel); padding:1px 4px; border-radius:4px; font-size:12px; }}
  .note {{ background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:10px 14px; font-size:13px; }}
</style>
</head>
<body>
<h1>🔬 HarScope 性能与合规分析报告</h1>
<div class="meta">
  来源 <code>{source}</code> · 标题 {title} · HAR 版本 {version} · 采集器 {creator} · 请求 {requests} 条
</div>

<h2>📊 核心指标</h2>
<div class="cards">
  {cards}
</div>

<h2>⏱ 瀑布图</h2>
<div class="wrap">{svg}</div>

<h2>🌐 域名分布</h2>
<div class="wrap">{domain_table}</div>

<h2>📦 资源类型分布</h2>
<div class="wrap">{mime_table}</div>

<h2>🐢 最慢请求 TOP 15</h2>
<div class="wrap">{slow_table}</div>

<h2>♻️ 重复请求</h2>
<div class="wrap">{dupe_table}</div>

<h2>🔒 安全与合规审计</h2>
{security_block}

{notes_block}

<footer>由零依赖 HAR 分析工作台 <strong>HarScope</strong> 生成 · 报告为单文件离线可用</footer>
</body>
</html>
"""


def to_html_report(
    analysis: HarAnalysis,
    *,
    audit: Optional[SecurityAudit] = None,
    waterfall_limit: int = 40,
) -> str:
    """生成一份自包含（内联 SVG + CSS）的 HTML 报告。

    :param analysis: 分析结果。
    :param audit: 可选安全审计结果。
    :param waterfall_limit: 瀑布图行数上限。
    """
    summary = analysis.summary_dict()
    cards = "\n".join(
        '<div class="card"><div class="k">{k}</div><div class="v">{v}</div><div class="s">{s}</div></div>'.format(
            k=_esc(label), v=_esc(value), s=_esc(sub)
        )
        for label, value, sub in _card_data(analysis)
    )
    security_block = _security_block(audit) if audit is not None else (
        '<div class="note">未执行安全审计（本轮分析未启用 --security）。</div>'
    )
    notes_block = ""
    if analysis.notes:
        items = "".join("<li>%s</li>" % _esc(note) for note in analysis.notes)
        notes_block = '<h2>⚠️ 数据质量提示</h2><div class="note"><ul>%s</ul></div>' % items

    return _HTML_TEMPLATE.format(
        title=_esc(summary["title"]),
        source=_esc(summary["source"]),
        version=_esc(summary["har_version"]),
        creator=_esc(summary["creator"]),
        requests=human_count(analysis.total_requests),
        cards=cards,
        svg=to_svg_waterfall(analysis, limit=waterfall_limit),
        domain_table=_table_html(
            ["域名", "请求数", "传输体积", "占比", "平均耗时", "错误"],
            [
                [
                    "<code>%s</code>" % _esc(stat.host),
                    human_count(stat.requests),
                    human_bytes(stat.transfer_bytes),
                    "%.1f%%" % (stat.transfer_ratio * 100),
                    human_ms(stat.avg_ms),
                    stat.errors,
                ]
                for stat in analysis.domain_stats(12)
            ],
            numeric_cols=(1, 2, 3, 4, 5),
        ),
        mime_table=_table_html(
            ["资源类型", "请求数", "传输体积", "解压体积", "压缩节省"],
            [
                [
                    "<code>%s</code>" % _esc(stat.mime_type),
                    human_count(stat.requests),
                    human_bytes(stat.transfer_bytes),
                    human_bytes(stat.uncompressed_bytes),
                    "%s（%.0f%%）" % (human_bytes(stat.saving_bytes), stat.saving_ratio * 100),
                ]
                for stat in analysis.mime_stats(12)
            ],
            numeric_cols=(1, 2, 3, 4),
        ),
        slow_table=_table_html(
            ["#", "方法", "URL", "耗时", "TTFB", "体积", "状态"],
            [
                [
                    entry.index,
                    entry.request.method,
                    "<code>%s</code>" % _esc(entry.request.display_path),
                    human_ms(entry.time_ms),
                    human_ms(entry.wait_ms),
                    human_bytes(entry.total_size),
                    entry.response.status or "-",
                ]
                for entry in analysis.slowest(15)
            ],
            numeric_cols=(0, 3, 4, 5, 6),
        ),
        dupe_table=_table_html_or_note(
            ["方法", "URL", "重复次数", "冗余体积"],
            [
                [
                    group.method,
                    "<code>%s</code>" % _esc(group.url[:90]),
                    group.count,
                    human_bytes(group.wasted_bytes),
                ]
                for group in analysis.duplicates(top=12)
            ],
            empty_note="🎉 未发现完全重复的请求。",
            numeric_cols=(2, 3),
        ),
        security_block=security_block,
        notes_block=notes_block,
    )


def _card_data(analysis: HarAnalysis) -> List[List[str]]:
    """生成 HTML 报告顶部的核心指标卡片数据。"""
    return [
        ["请求总数", human_count(analysis.total_requests),
         "涉及 %s 个域名" % human_count(analysis.unique_hosts)],
        ["会话跨度", human_ms(analysis.duration_ms),
         "并发度 %.2f×" % analysis.parallelism],
        ["总传输体积", human_bytes(analysis.transfer_bytes),
         "头部占 %.1f%%" % (analysis.header_ratio * 100)],
        ["响应体（压缩后）", human_bytes(analysis.body_transfer_bytes),
         "解压后 %s" % human_bytes(analysis.uncompressed_body_bytes)],
        ["压缩收益", human_bytes(analysis.compression_saving_bytes),
         "节省 %.1f%%" % (analysis.compression_saving_ratio * 100)],
        ["TTFB 平均", human_ms(analysis.average_wait_ms),
         "P95 耗时 %s" % human_ms(analysis.p95_ms)],
        ["HTTPS 占比", "%.1f%%" % (analysis.https_ratio * 100),
         "明文请求 %d 条" % analysis.insecure_requests],
        ["缓存命中", "%.1f%%" % (analysis.cache_hit_ratio * 100),
         "命中 %d 条" % analysis.cache_hits],
    ]


def _security_block(audit: SecurityAudit) -> str:
    """渲染安全审计区块（评分 + 发现列表）。"""
    head = (
        '<div class="cards"><div class="card"><div class="k">综合安全评分</div>'
        '<div class="score">%d</div><div class="grade">%s 级 · 共 %d 条发现</div></div>'
        '<div class="card"><div class="k">高危 / 中危 / 低危</div>'
        '<div class="v">%d / %d / %d</div><div class="s">HTTPS 占比 %.1f%%</div></div></div>'
        % (
            audit.score, audit.grade, len(audit.findings),
            audit.high_count, audit.medium_count, audit.low_count,
            audit.https_ratio * 100,
        )
    )
    rows = [
        [
            '<span class="tag %s">%s</span>' % (f.severity, f.severity_label),
            f.category,
            _esc(f.message),
            "<code>%s</code>" % _esc(f.url[:70]) if f.url else "",
            _esc(f.hint),
        ]
        for f in audit.findings[:40]
    ]
    table = _table_html_or_note(
        ["等级", "类别", "说明", "证据", "修复建议"],
        rows,
        empty_note="🎉 未发现明显的安全或合规问题。",
    )
    return head + table


def _table_html(headers: Sequence[str], rows: Sequence[Sequence[Any]],
                *, numeric_cols: Sequence[int] = ()) -> str:
    """渲染通用 HTML 表格。"""
    head = "".join(
        '<th class="%s">%s</th>' % ("num" if i in numeric_cols else "", _esc(h))
        for i, h in enumerate(headers)
    )
    body = []
    for row in rows:
        cells = "".join(
            '<td class="%s">%s</td>' % ("num" if i in numeric_cols else "", cell)
            for i, cell in enumerate(row)
        )
        body.append("<tr>%s</tr>" % cells)
    return (
        '<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
        % (head, "\n".join(body))
    )


def _table_html_or_note(headers: Sequence[str], rows: Sequence[Sequence[Any]],
                        *, empty_note: str, numeric_cols: Sequence[int] = ()) -> str:
    """有数据渲染表格，无数据渲染友好提示。"""
    if not rows:
        return '<div class="note">%s</div>' % _esc(empty_note)
    return _table_html(headers, rows, numeric_cols=numeric_cols)


# --------------------------------------------------------------------------
# 写盘入口
# --------------------------------------------------------------------------
def write_export(
    content: str,
    destination: Union[str, "os.PathLike[str]"],
    *,
    force: bool = False,
) -> str:
    """把导出内容写入文件。

    :param content: 文本内容。
    :param destination: 目标路径；父目录不存在时自动创建。
    :param force: 目标文件已存在时是否覆盖。
    :raises ExportError: 路径已存在且未开启覆盖，或写入失败。
    :returns: 实际写入的路径。
    """
    import os

    path = os.fspath(destination)
    if os.path.exists(path) and not force:
        raise ExportError("目标文件已存在：%s（使用 --force 覆盖）" % path)
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise ExportError("无法创建目录 %s：%s" % (directory, exc)) from exc
    try:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
    except OSError as exc:
        raise ExportError("写入失败 %s：%s" % (path, exc)) from exc
    return path
