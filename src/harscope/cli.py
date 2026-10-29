"""命令行入口。

命令组织遵循「一个命令回答一个问题」的原则，方便在管道里组合::

    harscope summary app.har
    harscope slow app.har --top 5
    harscope ci app.har --max-load-ms 3000 --require-security-headers

所有命令都支持 ``--json`` 输出结构化结果；``ci`` 额外通过退出码表达结论
（``0`` 通过 / ``1`` 不达标 / ``2`` 输入错误）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from . import __version__
from .analyze import HarAnalysis, analyze
from .exceptions import ExportError, HarScopeError, NetworkRecordError
from .exporters import (
    FORMATS,
    to_csv,
    to_html_report,
    to_json,
    to_markdown,
    to_svg_waterfall,
    write_export,
)
from .exceptions import HarParserError
from .model import Har
from .parser import load
from .recorder import RecordOptions, record
from .render import (
    Palette,
    bar,
    human_bytes,
    human_count,
    human_ms,
    render_waterfall,
    rule,
    table,
)
from .security import SECURITY_HEADERS, audit

__all__ = ["main", "build_parser"]

#: 退出码语义（供 CI/脚本消费）。
EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_ERROR = 2

PROGRAM = "harscope"

BANNER = "🔬 HarScope %s · 零依赖 HAR 分析工作台" % __version__


# --------------------------------------------------------------------------
# 命令行构造
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """构造完整的 argparse 解析器。"""
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="🔬 HarScope —— 零依赖的 HTTP Archive (HAR) 分析与性能取证工作台",
        epilog=(
            "示例：\n"
            "  harscope summary app.har            # 会话总览\n"
            "  harscope slow app.har --top 5       # 最慢的 5 个请求\n"
            "  harscope waterfall app.har          # 终端瀑布图\n"
            "  harscope security app.har           # 安全与合规审计\n"
            "  harscope report app.har -o out.html # 单文件 HTML 报告\n"
            "  harscope ci app.har --max-load-ms 3000\n"
            "  harscope record https://example.com -o trace.har\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="关闭 ANSI 颜色输出（等价于设置 NO_COLOR=1）",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="以 JSON 输出结果，便于二次处理",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    def attach(name: str, *, help_text: str, har_positional: bool = True):
        """快速创建一个子命令解析器并挂上通用参数。"""
        sub = subparsers.add_parser(name, help=help_text, description=help_text)
        if har_positional:
            sub.add_argument("har", help="HAR 文件路径（`-` 表示从标准输入读取）")
        return sub

    summary = attach("summary", help_text="会话总览：规模、体积、耗时、状态码分布")
    summary.add_argument("--top", type=int, default=10, help="域名/MIME TOP-N 上限（默认 10）")

    attach("waterfall", help_text="在终端绘制请求瀑布图").add_argument(
        "--top",
        type=int,
        default=30,
        help="最多绘制多少行；超过上限时保留最慢的 N 条（默认 30）",
    )

    attach("domains", help_text="按域名聚合的请求/体积/耗时分布").add_argument(
        "--top", type=int, default=15, help="返回行数（默认 15）"
    )

    attach("mime", help_text="按 MIME 类型聚合的资源体积分布").add_argument(
        "--top", type=int, default=15, help="返回行数（默认 15）"
    )

    slow = attach("slow", help_text="最慢的请求")
    slow.add_argument("--top", type=int, default=10, help="返回行数（默认 10）")
    slow.add_argument(
        "--by",
        choices=("time", "wait"),
        default="time",
        help="排序依据：time=总耗时，wait=等待首字节（默认 time）",
    )

    big = attach("largest", help_text="传输体积最大的请求")
    big.add_argument("--top", type=int, default=10, help="返回行数（默认 10）")

    attach("status", help_text="状态码分布")

    attach("pages", help_text="按页面聚合的加载情况")

    attach("dupes", help_text="完全重复的请求（同方法+同 URL）").add_argument(
        "--top", type=int, default=10, help="返回组数（默认 10）"
    )

    security = attach("security", help_text="安全与响应头合规审计")
    security.add_argument(
        "--fail-on",
        choices=("high", "medium", "low", "none"),
        default="none",
        help="出现指定等级及以上的发现时以退出码 1 结束（默认 none）",
    )

    export = attach("export", help_text="导出为 JSON / CSV / Markdown / SVG / HTML")
    export.add_argument(
        "--format",
        default="json",
        choices=sorted(FORMATS),
        help="导出格式（默认 json）",
    )
    export.add_argument("-o", "--output", required=True, help="输出文件路径")
    export.add_argument("--force", action="store_true", help="目标文件存在时覆盖")
    export.add_argument("--entries", action="store_true", help="JSON 导出时附带逐条明细")
    export.add_argument("--no-security", action="store_true", help="跳过安全审计")
    export.add_argument("--waterfall-rows", type=int, default=40, help="HTML/SVG 瀑布图行数")

    report = attach("report", help_text="生成自包含的单文件 HTML 报告")
    report.add_argument("-o", "--output", default="harscope-report.html", help="输出路径")
    report.add_argument("--force", action="store_true", help="目标存在时覆盖")
    report.add_argument("--no-security", action="store_true", help="跳过安全审计")
    report.add_argument("--waterfall-rows", type=int, default=40, help="瀑布图行数")

    ci = attach("ci", help_text="CI 质量门禁：用退出码表达是否达标")
    ci.add_argument("--max-requests", type=int, help="请求总数上限")
    ci.add_argument("--max-transfer-kb", type=float, help="总传输体积上限（KB）")
    ci.add_argument("--max-load-ms", type=float, help="会话跨度上限（毫秒）")
    ci.add_argument("--max-p95-ms", type=float, help="请求耗时 P95 上限（毫秒）")
    ci.add_argument("--min-cache-ratio", type=float, help="缓存命中率下限（0~1）")
    ci.add_argument("--require-https", action="store_true", help="要求全部走 HTTPS")
    ci.add_argument(
        "--require-security-headers",
        action="store_true",
        help="要求文档响应具备 HSTS/CSP/nosniff",
    )
    ci.add_argument("--max-duplicate-requests", type=int, help="允许的重复请求组数上限")
    ci.add_argument(
        "--max-findings",
        type=int,
        help="允许的安全发现总数上限（未设置则不检查安全项）",
    )

    rec = attach("record", help_text="录制网页加载过程为 HAR 文件", har_positional=False)
    rec.add_argument("url", help="要抓取的目标 URL")
    rec.add_argument("-o", "--output", default="trace.har", help="输出 HAR 路径")
    rec.add_argument("--force", action="store_true", help="目标存在时覆盖")
    rec.add_argument("--timeout", type=float, default=10.0, help="单请求超时（秒，默认 10）")
    rec.add_argument("--assets", type=int, default=12, help="最多抓取多少个一级静态资源（默认 12）")
    rec.add_argument("--max-redirects", type=int, default=5, help="最大跳转次数（默认 5）")
    rec.add_argument("--user-agent", help="自定义 User-Agent")
    rec.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME:VALUE",
        help="附加请求头，可重复指定",
    )
    rec.add_argument("--cross-host", action="store_true", help="允许抓取跨域名资源")
    rec.add_argument("--insecure", action="store_true", help="跳过 TLS 证书校验（仅供内网自测）")

    doctor = attach("doctor", help_text="自检运行环境与依赖", har_positional=False)
    doctor.set_defaults(func=None)

    return parser


# --------------------------------------------------------------------------
# 命令实现
# --------------------------------------------------------------------------
def _pad(text: str, width: int) -> str:
    """按显示宽度补齐，避免中英文混排时列错位。"""
    from .render import _display_width

    gap = width - _display_width(text)
    return text if gap <= 0 else text + " " * gap


def _load_har(path: str) -> Har:
    """读取并解析 HAR，统一错误出口。"""
    return load(path)


def cmd_summary(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """输出会话总览。"""
    summary = analysis.summary_dict()
    if args.as_json:
        return summary

    print(rule("会话总览"))
    print(
        "%s %s\n%s 请求 %s 条 ｜ 域名 %s 个 ｜ HAR %s ｜ 采集器 %s"
        % (
            Palette.cyan(Palette.bold("🔬 HAR 会话")),
            analysis.har.title,
            Palette.grey("·"),
            Palette.bold(human_count(analysis.total_requests)),
            Palette.bold(human_count(analysis.unique_hosts)),
            analysis.har.version,
            summary["creator"],
        )
    )
    print()

    cards = [
        ("会话跨度", human_ms(analysis.duration_ms)),
        ("累计耗时", human_ms(analysis.total_time_ms)),
        ("并发度", "%.2f×" % analysis.parallelism),
        ("平均耗时", human_ms(analysis.average_ms)),
        ("P50", human_ms(analysis.p50_ms)),
        ("P95", human_ms(analysis.p95_ms)),
        ("平均 TTFB", human_ms(analysis.average_wait_ms)),
        ("总传输", human_bytes(analysis.transfer_bytes)),
        ("响应体", human_bytes(analysis.body_transfer_bytes)),
        ("头部", "%s（%.1f%%）" % (human_bytes(analysis.header_bytes),
                                  analysis.header_ratio * 100)),
        ("解压体积", human_bytes(analysis.uncompressed_body_bytes)),
        ("压缩节省", "%s（%.1f%%）" % (human_bytes(analysis.compression_saving_bytes),
                                      analysis.compression_saving_ratio * 100)),
        ("HTTPS", "%.1f%%" % (analysis.https_ratio * 100)),
        ("缓存命中", "%.1f%%" % (analysis.cache_hit_ratio * 100)),
    ]
    width = 2
    for index in range(0, len(cards), width):
        chunk = cards[index: index + width]
        print("  ".join(
            "%s %s" % (Palette.grey(_pad(name, 12)), Palette.bold(_pad(value, 17)))
            for name, value in chunk
        ).rstrip())
    print()

    classes = analysis.status_classes
    print(Palette.bold("状态码分布"))
    total = max(analysis.total_requests, 1)
    for key in sorted(classes):
        count = classes[key]
        color = Palette.green
        if key.startswith(("4", "5")):
            color = Palette.red
        elif key.startswith("3"):
            color = Palette.yellow
        print(
            "  %s %s %s %s" % (
                Palette.cyan(key),
                color(bar(count / total, 28)),
                Palette.bold(human_count(count).rjust(7)),
                Palette.grey("%.1f%%" % (count / total * 100)),
            )
        )
    print()

    print(Palette.bold("域名 TOP%d" % args.top))
    rows = []
    for stat in analysis.domain_stats(args.top):
        rows.append([
            stat.host,
            human_count(stat.requests),
            human_bytes(stat.transfer_bytes),
            bar(stat.transfer_ratio, 18),
            human_ms(stat.avg_ms),
            stat.errors or "",
        ])
    print(table(
        ["域名", "请求数", "传输体积", "占比", "平均耗时", "错误"],
        rows,
        aligns=["left", "right", "right", "left", "right", "right"],
    ))
    print()

    print(Palette.bold("资源类型 TOP%d" % args.top))
    rows = []
    for stat in analysis.mime_stats(args.top):
        rows.append([
            stat.mime_type,
            human_count(stat.requests),
            human_bytes(stat.transfer_bytes),
            human_bytes(stat.uncompressed_bytes),
            "%.1f%%" % (stat.saving_ratio * 100) if stat.saving_bytes else "-",
        ])
    print(table(
        ["MIME", "请求数", "传输体积", "解压体积", "压缩节省"],
        rows,
        aligns=["left", "right", "right", "right", "right"],
    ))
    if analysis.notes:
        print()
        print(Palette.yellow("⚠️  数据质量提示"))
        for note in analysis.notes:
            print("  - %s" % note)
    print()
    return summary


def cmd_waterfall(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """绘制终端瀑布图。"""
    rows = analysis.waterfall(limit=args.top)
    if args.as_json:
        return {
            "rows": [
                {
                    "index": row.entry.index,
                    "url": row.entry.url,
                    "offset_ms": round(row.offset_ms, 2),
                    "duration_ms": round(row.duration_ms, 2),
                    "phases": [{"phase": p, "ms": round(v, 2)} for p, v in row.phases],
                }
                for row in rows
            ]
        }
    print(render_waterfall(rows, max_rows=args.top))
    print()
    return {"rows": len(rows)}


def cmd_domains(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """域名分布表。"""
    rows = []
    payload = []
    for stat in analysis.domain_stats(args.top):
        payload.append({
            "host": stat.host,
            "requests": stat.requests,
            "transfer_bytes": stat.transfer_bytes,
            "header_bytes": stat.header_bytes,
            "transfer_ratio": round(stat.transfer_ratio, 4),
            "avg_ms": round(stat.avg_ms, 2),
            "wait_ms": round(stat.wait_ms, 2),
            "errors": stat.errors,
            "secure": stat.secure,
        })
        rows.append([
            stat.host,
            "" if stat.secure else Palette.red("明文"),
            human_count(stat.requests),
            human_bytes(stat.transfer_bytes),
            "%.1f%%" % (stat.transfer_ratio * 100),
            human_ms(stat.avg_ms),
            human_ms(stat.wait_ms),
            stat.errors or "",
        ])
    if args.as_json:
        return {"domains": payload}
    print(table(
        ["域名", "安全", "请求数", "传输体积", "占比", "平均耗时", "累计 TTFB", "错误"],
        rows,
        aligns=["left", "center", "right", "right", "right", "right", "right", "right"],
    ))
    print()
    return {"domains": payload}


def cmd_mime(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """MIME 分布表。"""
    payload = []
    rows = []
    for stat in analysis.mime_stats(args.top):
        payload.append({
            "mime_type": stat.mime_type,
            "requests": stat.requests,
            "transfer_bytes": stat.transfer_bytes,
            "uncompressed_bytes": stat.uncompressed_bytes,
            "saving_bytes": stat.saving_bytes,
        })
        rows.append([
            stat.mime_type,
            human_count(stat.requests),
            human_bytes(stat.transfer_bytes),
            human_bytes(stat.uncompressed_bytes),
            human_bytes(stat.saving_bytes),
            "%.1f%%" % (stat.saving_ratio * 100) if stat.saving_bytes else "-",
        ])
    if args.as_json:
        return {"mime": payload}
    print(table(
        ["MIME", "请求数", "传输体积", "解压体积", "压缩节省", "节省率"],
        rows,
        aligns=["left", "right", "right", "right", "right", "right"],
    ))
    print()
    return {"mime": payload}


def cmd_slow(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """最慢请求排行。"""
    entries = analysis.slowest(args.top, by=args.by)
    payload = [
        {
            "index": e.index,
            "method": e.request.method,
            "url": e.url,
            "status": e.response.status,
            "time_ms": round(e.time_ms, 2),
            "wait_ms": round(e.wait_ms, 2),
            "transfer_bytes": e.total_size,
        }
        for e in entries
    ]
    if args.as_json:
        return {"slowest": payload}
    rows = []
    for entry in entries:
        color = Palette.red if entry.time_ms >= analysis.p95_ms else Palette.bold
        rows.append([
            entry.index,
            entry.request.method,
            entry.request.display_path,
            color(human_ms(entry.time_ms)),
            human_ms(entry.wait_ms),
            human_bytes(entry.total_size),
            entry.response.status or "-",
        ])
    print(rule("最慢请求 TOP%d（按 %s 排序）" % (args.top, "总耗时" if args.by == "time" else "TTFB")))
    print(table(
        ["#", "方法", "URL", "耗时", "TTFB", "体积", "状态"],
        rows,
        aligns=["right", "left", "left", "right", "right", "right", "right"],
    ))
    print()
    return {"slowest": payload}


def cmd_largest(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """体积最大的请求排行。"""
    entries = analysis.largest(args.top)
    payload = [
        {
            "index": e.index,
            "url": e.url,
            "mime": e.response.mime_type,
            "transfer_bytes": e.total_size,
            "uncompressed_bytes": e.response.uncompressed_body_size,
            "time_ms": round(e.time_ms, 2),
        }
        for e in entries
    ]
    if args.as_json:
        return {"largest": payload}
    rows = []
    for entry in entries:
        rows.append([
            entry.index,
            entry.request.display_path,
            entry.response.mime_type or "-",
            human_bytes(entry.total_size),
            human_bytes(entry.response.uncompressed_body_size),
            human_ms(entry.time_ms),
        ])
    print(rule("传输体积 TOP%d" % args.top))
    print(table(
        ["#", "URL", "MIME", "传输体积", "解压体积", "耗时"],
        rows,
        aligns=["right", "left", "left", "right", "right", "right"],
    ))
    print()
    return {"largest": payload}


def cmd_status(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """状态码分布。"""
    payload = {
        "classes": analysis.status_classes,
        "codes": {str(k): v for k, v in sorted(analysis.status_codes.items())},
        "errors": [
            {"url": e.url, "status": e.response.status, "index": e.index}
            for e in analysis.error_entries[:50]
        ],
        "client_errors": [
            {"url": e.url, "status": e.response.status, "index": e.index}
            for e in analysis.client_error_entries[:50]
        ],
    }
    if args.as_json:
        return payload
    rows = []
    for code, count in sorted(analysis.status_codes.items()):
        color = Palette.green
        if code >= 500:
            color = Palette.red
        elif code >= 400:
            color = Palette.yellow
        label = "%d" % code if code else "-"
        rows.append([color(label), human_count(count),
                     bar(count / max(analysis.total_requests, 1), 32)])
    print(rule("状态码分布"))
    print(table(["状态码", "数量", "占比"], rows,
                aligns=["right", "right", "left"]))
    for entry in analysis.error_entries[:5]:
        print(Palette.red("  5xx：%s %s" % (entry.response.status, entry.request.display_path)))
    print()
    return payload


def cmd_pages(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """页面维度聚合。"""
    payload = [
        {
            "page_id": page.page_id,
            "title": page.title,
            "requests": page.requests,
            "transfer_bytes": page.transfer_bytes,
            "duration_ms": round(page.duration_ms, 2),
            "on_load_ms": page.on_load_ms,
            "on_content_load_ms": page.on_content_load_ms,
        }
        for page in analysis.page_stats()
    ]
    if args.as_json:
        return {"pages": payload}
    rows = []
    for page in analysis.page_stats():
        rows.append([
            page.page_id,
            page.title[:38],
            human_count(page.requests),
            human_bytes(page.transfer_bytes),
            human_ms(page.duration_ms),
            human_ms(page.on_content_load_ms or 0) if page.on_content_load_ms else "-",
            human_ms(page.on_load_ms or 0) if page.on_load_ms else "-",
        ])
    print(rule("页面加载概览"))
    print(table(
        ["页面 ID", "标题", "请求数", "传输体积", "跨度", "DOMContentLoaded", "onLoad"],
        rows,
        aligns=["left", "left", "right", "right", "right", "right", "right"],
    ))
    print()
    return {"pages": payload}


def cmd_dupes(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """重复请求分析。"""
    groups = analysis.duplicates(top=args.top)
    payload = [
        {
            "method": g.method,
            "url": g.url,
            "count": g.count,
            "transfer_bytes": g.transfer_bytes,
            "wasted_bytes": g.wasted_bytes,
        }
        for g in groups
    ]
    if args.as_json:
        return {"duplicates": payload}
    print(rule("重复请求"))
    if not groups:
        print(Palette.green("🎉 未发现完全重复的请求。"))
        print()
        return {"duplicates": []}
    rows = [
        [
            g.method,
            g.url[:70],
            g.count,
            human_bytes(g.transfer_bytes),
            Palette.yellow(human_bytes(g.wasted_bytes)),
        ]
        for g in groups
    ]
    print(table(
        ["方法", "URL", "次数", "总传输", "冗余体积"],
        rows,
        aligns=["left", "left", "right", "right", "right"],
    ))
    wasted = sum(g.wasted_bytes for g in analysis.duplicates(top=10 ** 6))
    print()
    print("去重后可节省约 %s 的重复传输。" % Palette.bold(human_bytes(wasted)))
    print()
    return {"duplicates": payload}


def cmd_security(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """安全审计。"""
    result = audit(analysis.har)
    payload = result.to_dict()
    if args.as_json:
        return payload

    print(rule("安全与合规审计"))
    grade_color = {
        "A": Palette.green, "B": Palette.green, "C": Palette.yellow,
        "D": Palette.red, "E": Palette.red,
    }.get(result.grade, Palette.bold)
    print(
        "%s %s  ｜ %s 高危 / %s 中危 / %s 低危 / %s 提示"
        % (
            Palette.bold("综合评分"),
            grade_color(Palette.bold("%d/100 %s 级" % (result.score, result.grade))),
            Palette.red(str(result.high_count)),
            Palette.yellow(str(result.medium_count)),
            Palette.blue(str(result.low_count)),
            Palette.grey(str(result.info_count)),
        )
    )
    print(
        "%s HTTPS %s ｜ 明文 %s ｜ 受检文档响应 %s 个"
        % (
            Palette.grey("·"),
            Palette.bold("%.1f%%" % (result.https_ratio * 100)),
            Palette.bold(human_count(result.http_requests)),
            Palette.bold(human_count(result.documents_checked)),
        )
    )
    print()

    if result.missing_header_counts:
        print(Palette.bold("缺失安全响应头统计"))
        rows = []
        for header, reason in SECURITY_HEADERS:
            count = result.missing_header_counts.get(header)
            if count:
                rows.append([header, human_count(count), reason])
        print(table(["响应头", "缺失数", "作用"], rows,
                    aligns=["left", "right", "left"]))
        print()

    print(Palette.bold("发现清单"))
    if not result.findings:
        print(Palette.green("🎉 没有发现明显的安全或合规问题。"))
    else:
        rows = []
        for finding in result.findings:
            rows.append([
                Palette.paint(
                    {"high": Palette.RED, "medium": Palette.YELLOW,
                     "low": Palette.BLUE, "info": Palette.GREY}.get(finding.severity, ""),
                    finding.severity_label,
                ),
                finding.category,
                finding.message,
                finding.url[:56],
            ])
        print(table(["等级", "类别", "说明", "证据"], rows,
                    aligns=["center", "left", "left", "left"]))
    print()
    return payload


def cmd_export(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """导出到文件。"""
    security = None if args.no_security else audit(analysis.har)
    fmt = FORMATS[args.format]
    if fmt in {"html", "svg"}:
        content = to_html_report(
            analysis, audit=security, waterfall_limit=args.waterfall_rows
        ) if fmt == "html" else to_svg_waterfall(analysis, limit=args.waterfall_rows)
    elif fmt == "json":
        content = to_json(analysis, audit=security, include_entries=args.entries)
    elif fmt == "csv":
        content = to_csv(analysis.entries)
    else:
        content = to_markdown(analysis, audit=security)

    path = write_export(content, args.output, force=args.force)
    if args.as_json:
        return {"format": fmt, "output": path, "bytes": len(content.encode("utf-8"))}
    print(Palette.green("✅ 已导出 %s → %s（%s）" % (
        fmt.upper(), path, human_bytes(len(content.encode("utf-8")))
    )))
    return {"format": fmt, "output": path}


def cmd_report(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """生成 HTML 报告（:func:`cmd_export` 的快捷形态）。"""
    args.format = "html"
    return cmd_export(args, analysis)


def cmd_ci(args: argparse.Namespace, analysis: HarAnalysis) -> Dict[str, Any]:
    """CI 质量门禁。"""
    checks: List[Dict[str, Any]] = []

    def record_check(name: str, ok: bool, actual: str, limit: str, hint: str) -> None:
        """登记一项检查结果。"""
        checks.append({"name": name, "ok": ok, "actual": actual, "limit": limit, "hint": hint})

    if args.max_requests is not None:
        record_check(
            "请求总数", analysis.total_requests <= args.max_requests,
            "%d 条" % analysis.total_requests, "≤ %d 条" % args.max_requests,
            "考虑合并资源、移除冗余第三方脚本。",
        )
    if args.max_transfer_kb is not None:
        actual_kb = analysis.transfer_bytes / 1024.0
        record_check(
            "总传输体积", actual_kb <= args.max_transfer_kb,
            human_bytes(analysis.transfer_bytes), "≤ %s KB" % human_count(args.max_transfer_kb),
            "开启 Brotli/gzip、压缩图片、按需加载。",
        )
    if args.max_load_ms is not None:
        record_check(
            "会话跨度", analysis.duration_ms <= args.max_load_ms,
            human_ms(analysis.duration_ms), "≤ %s" % human_ms(args.max_load_ms),
            "减少关键请求链长度、启用预连接。",
        )
    if args.max_p95_ms is not None:
        record_check(
            "P95 耗时", analysis.p95_ms <= args.max_p95_ms,
            human_ms(analysis.p95_ms), "≤ %s" % human_ms(args.max_p95_ms),
            "优化慢接口或引入缓存层。",
        )
    if args.min_cache_ratio is not None:
        record_check(
            "缓存命中率", analysis.cache_hit_ratio >= args.min_cache_ratio,
            "%.1f%%" % (analysis.cache_hit_ratio * 100),
            "≥ %.1f%%" % (args.min_cache_ratio * 100),
            "为静态资源设置长期 Cache-Control。",
        )
    if args.require_https:
        record_check(
            "全站 HTTPS", analysis.insecure_requests == 0,
            "%d 条明文" % analysis.insecure_requests, "0 条明文",
            "统一替换为 https:// 并开启 HSTS。",
        )
    if args.max_duplicate_requests is not None:
        count = len(analysis.duplicates(top=10 ** 6))
        record_check(
            "重复请求组数", count <= args.max_duplicate_requests,
            "%d 组" % count, "≤ %d 组" % args.max_duplicate_requests,
            "去重后再发起，或增加本地缓存层。",
        )

    security = None
    if args.max_findings is not None or args.require_security_headers:
        security = audit(analysis.har)
    if security is not None:
        if args.max_findings is not None:
            record_check(
                "安全发现总数", len(security.findings) <= args.max_findings,
                "%d 条" % len(security.findings), "≤ %d 条" % args.max_findings,
                "按 `harscope security` 输出逐项修复。",
            )
        if args.require_security_headers:
            critical = {"strict-transport-security", "content-security-policy",
                        "x-content-type-options"}
            missing = sum(
                count for header, count in security.missing_header_counts.items()
                if header in critical
            )
            record_check(
                "关键安全响应头", missing == 0,
                "%d 处缺失" % missing, "0 处缺失",
                "在网关统一注入 HSTS / CSP / nosniff。",
            )

    failures = [c for c in checks if not c["ok"]]
    payload = {
        "passed": not failures,
        "checks": checks,
        "failed_count": len(failures),
    }
    if args.as_json:
        return payload

    print(rule("CI 质量门禁"))
    if not checks:
        print(Palette.yellow("未指定任何阈值，跳过检查。可用 --max-requests 等参数定义门禁。"))
        return payload
    rows = [
        [
            Palette.green("✅ PASS") if c["ok"] else Palette.red("❌ FAIL"),
            c["name"],
            c["actual"],
            Palette.grey(c["limit"]),
            c["hint"] if not c["ok"] else "",
        ]
        for c in checks
    ]
    print(table(["结果", "检查项", "实测", "阈值", "建议"], rows,
                aligns=["left", "left", "right", "right", "left"]))
    print()
    if failures:
        print(Palette.red("❌ %d/%d 项未达标" % (len(failures), len(checks))))
    else:
        print(Palette.green("✅ 全部 %d 项检查通过" % len(checks)))
    print()
    return payload


def cmd_record(args: argparse.Namespace, _analysis: Optional[HarAnalysis] = None) -> Dict[str, Any]:
    """录制 HAR。"""
    headers: Dict[str, str] = {}
    for raw in args.header or []:
        if ":" not in raw:
            raise ExportError("请求头格式应为 NAME:VALUE，收到：%s" % raw)
        name, value = raw.split(":", 1)
        headers[name.strip()] = value.strip()

    options = RecordOptions(
        timeout=args.timeout,
        max_assets=args.assets,
        max_redirects=args.max_redirects,
        user_agent=args.user_agent or RecordOptions.user_agent,
        headers=headers,
        insecure=args.insecure,
        same_host_only=not args.cross_host,
    )
    har = record(args.url, options)
    content = json.dumps(har, ensure_ascii=False, indent=2)
    path = write_export(content, args.output, force=args.force)
    entries = har["log"]["entries"]
    total_bytes = sum(e["response"].get("_transferSize") or 0 for e in entries)
    payload = {
        "output": path,
        "requests": len(entries),
        "transfer_bytes": total_bytes,
    }
    if args.as_json:
        return payload
    print(Palette.green("✅ 已录制 %s → %s" % (args.url, path)))
    print(
        "%s 记录 %s 条 ｜ 有效载荷约 %s ｜ 响应体内容未被保存"
        % (
            Palette.grey("·"),
            Palette.bold(human_count(len(entries))),
            Palette.bold(human_bytes(total_bytes)),
        )
    )
    return payload


def cmd_doctor(args: argparse.Namespace, _analysis: Optional[HarAnalysis] = None) -> Dict[str, Any]:
    """环境自检。"""
    import platform

    info = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "harscope": __version__,
        "third_party_dependencies": 0,
        "color": _color_state(),
        "checks": [],
    }

    def check(name: str, ok: bool, detail: str) -> None:
        """登记一项环境检查。"""
        info["checks"].append({"name": name, "ok": ok, "detail": detail})

    check("Python 版本 ≥ 3.8", sys.version_info >= (3, 8),
          platform.python_version())
    check("标准库 http.client 可用", True, "已内置")
    check("标准库 ssl 可用", _ssl_ok(), _ssl_detail())
    check("标准输出是否被管道重定向", not sys.stdout.isatty(),
          "管道模式（会自动关闭颜色）" if not sys.stdout.isatty() else "交互模式")
    if args.as_json:
        return info

    print(rule("环境自检"))
    print("%s HarScope %s ｜ Python %s ｜ %s" % (
        Palette.cyan(Palette.bold("🔬")), __version__, info["python"], info["platform"],
    ))
    rows = [
        [Palette.green("✅") if c["ok"] else Palette.red("⚠️"), c["name"], c["detail"]]
        for c in info["checks"]
    ]
    print(table(["", "检查项", "详情"], rows, aligns=["center", "left", "left"]))
    print()
    print(Palette.grey("本工具零第三方依赖，离线可用。"))
    print()
    return info


def _color_state() -> str:
    """当前配色状态字符串。"""
    from .render import PALETTE

    return "enabled" if PALETTE.enabled else "disabled"


def _ssl_ok() -> bool:
    """ssl 模块是否可用。"""
    try:
        import ssl  # noqa: F401

        return True
    except ImportError:  # pragma: no cover
        return False


def _ssl_detail() -> str:
    """ssl 版本信息。"""
    import ssl

    return getattr(ssl, "OPENSSL_VERSION", "unknown")


#: 命令名到实现函数的映射。
COMMANDS = {
    "summary": cmd_summary,
    "waterfall": cmd_waterfall,
    "domains": cmd_domains,
    "mime": cmd_mime,
    "slow": cmd_slow,
    "largest": cmd_largest,
    "status": cmd_status,
    "pages": cmd_pages,
    "dupes": cmd_dupes,
    "security": cmd_security,
    "export": cmd_export,
    "report": cmd_report,
    "ci": cmd_ci,
    "record": cmd_record,
    "doctor": cmd_doctor,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行主入口。

    :param argv: 参数列表，默认取 ``sys.argv[1:]``。
    :returns: 进程退出码（见模块顶部常量说明）。
    """
    args = build_parser().parse_args(argv)

    if args.no_color:
        os.environ["NO_COLOR"] = "1"
        from .render import PALETTE

        PALETTE.reset()

    if not getattr(args, "command", None):
        build_parser().print_help()
        return EXIT_OK

    handler = COMMANDS[args.command]
    try:
        if getattr(args, "har", None) is not None:
            har = _load_har(args.har)
            analysis = analyze(har)
            result: Dict[str, Any] = handler(args, analysis)
        else:
            result = handler(args, None)
    except KeyboardInterrupt:  # pragma: no cover
        print(Palette.yellow("\n已中止。"), file=sys.stderr)
        return EXIT_ERROR
    except HarParserError as exc:
        print(Palette.red("❌ %s" % exc), file=sys.stderr)
        return EXIT_ERROR
    except NetworkRecordError as exc:
        print(Palette.red("🌐 %s" % exc), file=sys.stderr)
        return EXIT_ERROR
    except HarScopeError as exc:
        print(Palette.red("❌ %s" % exc), file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(Palette.red("❌ IO 错误：%s" % exc), file=sys.stderr)
        return EXIT_ERROR

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.command == "ci":
        return EXIT_OK if result.get("passed", True) else EXIT_VIOLATION
    if args.command == "security":
        # fail-on 语义：只有「阈值等级及以上」确实存在发现时才判失败。
        threshold = getattr(args, "fail_on", "none")
        if threshold == "none":
            return EXIT_OK
        counts = result.get("counts", {})
        ordered = [
            ("high", counts.get("high", 0)),
            ("medium", counts.get("medium", 0)),
            ("low", counts.get("low", 0)),
        ]
        if threshold == "high":
            candidates = ordered[:1]
        elif threshold == "medium":
            candidates = ordered[:2]
        else:
            candidates = ordered
        return EXIT_VIOLATION if any(count for _level, count in candidates) else EXIT_OK
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
