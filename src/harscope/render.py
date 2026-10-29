"""终端渲染辅助：配色、人类可读单位、表格与条形图。

设计原则：

* **永远可以被管道消费**：检测不到 TTY 或设置了 ``NO_COLOR`` 时自动关闭 ANSI 颜色；
* **绝不依赖第三方**：没有 rich / colorama，纯标准库实现；
* **宽度自适应**：读取 ``COLUMNS`` 环境变量，取不到时退到 100 列并居中截断。
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "Palette",
    "PaletteState",
    "supports_color",
    "human_bytes",
    "human_ms",
    "human_count",
    "table",
    "bar",
    "rule",
    "truncate",
    "render_waterfall",
]

#: 不同度量下的字节单位组。
_UNITS: Tuple[str, ...] = ("B", "KB", "MB", "GB", "TB", "PB")


class PaletteState:
    """全局配色开关。

    可通过环境变量控制：

    ``NO_COLOR``      任意非空值 → 强制关闭颜色
    ``HARSCOPE_FORCE_COLOR``  ``1`` → 强制开启颜色
    """

    def __init__(self) -> None:
        raw = os.environ.get("NO_COLOR")
        forced = os.environ.get("HARSCOPE_FORCE_COLOR")
        self.enabled: bool = bool(forced and forced != "0") or (
            not raw and _stream_is_tty()
        )

    def reset(self) -> None:
        """按当前环境变量重新计算开关状态（测试用）。"""
        raw = os.environ.get("NO_COLOR")
        forced = os.environ.get("HARSCOPE_FORCE_COLOR")
        self.enabled = bool(forced and forced != "0") or (not raw and _stream_is_tty())


def _stream_is_tty() -> bool:
    """标准输出是否为交互式终端。"""
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):  # pragma: no cover
        return False


def supports_color() -> bool:
    """当前是否应该输出 ANSI 颜色。"""
    return PALETTE.enabled


PALETTE = PaletteState()


class Palette:
    """一组语义化颜色常量，禁用配色时自动退化为空字符串。"""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GREY = "\033[90m"

    @classmethod
    def paint(cls, color: str, text: str) -> str:
        """给文本加上颜色，配色关闭时原样返回。"""
        if not PALETTE.enabled:
            return text
        return "%s%s%s" % (color, text, cls.RESET)

    @classmethod
    def red(cls, text: str) -> str:
        """红色（错误/高危）。"""
        return cls.paint(cls.RED, text)

    @classmethod
    def green(cls, text: str) -> str:
        """绿色（正常/优秀）。"""
        return cls.paint(cls.GREEN, text)

    @classmethod
    def yellow(cls, text: str) -> str:
        """黄色（警告/中等）。"""
        return cls.paint(cls.YELLOW, text)

    @classmethod
    def blue(cls, text: str) -> str:
        """蓝色（信息）。"""
        return cls.paint(cls.BLUE, text)

    @classmethod
    def cyan(cls, text: str) -> str:
        """青色（标题）。"""
        return cls.paint(cls.CYAN, text)

    @classmethod
    def magenta(cls, text: str) -> str:
        """洋红（强调）。"""
        return cls.paint(cls.MAGENTA, text)

    @classmethod
    def grey(cls, text: str) -> str:
        """灰色（次要信息）。"""
        return cls.paint(cls.GREY, text)

    @classmethod
    def bold(cls, text: str) -> str:
        """加粗。"""
        return cls.paint(cls.BOLD, text)


def terminal_width(default: int = 100) -> int:
    """当前终端可用宽度。"""
    try:
        width = shutil.get_terminal_size((default, 24)).columns
    except (AttributeError, ValueError):  # pragma: no cover
        width = default
    env = os.environ.get("COLUMNS")
    if env:
        try:
            width = int(env)
        except ValueError:
            pass
    return max(40, min(width, 200))


def human_bytes(size: Optional[float]) -> str:
    """把字节数格式化成人类可读字符串。

    >>> human_bytes(2048)
    '2.0 KB'
    """
    value = float(size or 0)
    if value < 0:
        return "-" + human_bytes(-value)
    index = 0
    while value >= 1024 and index < len(_UNITS) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return "%d %s" % (int(value), _UNITS[index])
    if value >= 100:
        return "%.0f %s" % (value, _UNITS[index])
    return "%.1f %s" % (value, _UNITS[index])


def human_ms(milliseconds: Optional[float]) -> str:
    """把毫秒格式化成人类可读字符串（超过 10 秒自动切到秒）。

    >>> human_ms(1234)
    '1.23 s'
    """
    value = float(milliseconds or 0)
    if value < 0:
        return "-" + human_ms(-value)
    if value >= 10_000:
        return "%.2f s" % (value / 1000.0)
    if value >= 1000:
        return "%.2f s" % (value / 1000.0)
    if value >= 100:
        return "%.0f ms" % value
    return "%.1f ms" % value


def human_count(value: float) -> str:
    """把计数格式化成千分位字符串。

    >>> human_count(1234567)
    '1,234,567'
    """
    return "{:,}".format(int(value))


def _display_width(text: str) -> int:
    """计算去除 ANSI 转义后、宽度感知的实际显示宽度（中日韩字符算 2 列）。"""
    import unicodedata

    stripped = _strip_ansi(text)
    width = 0
    for char in stripped:
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def _strip_ansi(text: str) -> str:
    """去掉字符串中的 ANSI 转义序列。"""
    import re

    return re.sub(r"\033\[[0-9;]*m", "", text)


def truncate(text: str, width: int, *, ellipsis: str = "…") -> str:
    """按显示宽度截断字符串，超出部分用省略号代替。"""
    if width <= 0:
        return ""
    if _display_width(text) <= width:
        return text
    budget = width - len(ellipsis)
    result = ""
    used = 0
    for char in text:
        step = 2 if _display_width(char) == 2 else 1
        if used + step > budget:
            break
        result += char
        used += step
    return result + ellipsis


def pad(text: str, width: int, *, align: str = "left") -> str:
    """按显示宽度补齐空格。"""
    gap = width - _display_width(text)
    if gap <= 0:
        return text
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    aligns: Optional[Sequence[str]] = None,
    max_width: Optional[int] = None,
) -> str:
    """渲染一张宽度自适应的纯文本表格。

    :param headers: 表头列。
    :param rows: 数据行（每行元素个数需与表头一致，内部会容错补齐）。
    :param aligns: 每列对齐方式，取值 ``left`` / ``right`` / ``center``。
    :param max_width: 表格总宽上限，默认自适应终端宽度。
    :returns: 拼好的多行字符串。
    """
    if not headers:
        return ""
    aligns = list(aligns or ["left"] * len(headers))
    widths = [ _display_width(h) for h in headers ]
    normalized: List[List[str]] = []
    for row in rows:
        cells = [str(c) for c in row] + [""] * (len(headers) - len(row))
        normalized.append(cells[: len(headers)])
        for i, cell in enumerate(cells[: len(headers)]):
            widths[i] = max(widths[i], _display_width(cell))

    limit = max_width or terminal_width()
    overhead = 3 * (len(headers) - 1) + 2
    available = max(20, limit - overhead)
    total_body = sum(widths)
    if total_body > available:
        # 优先压缩最宽的列，保证关键信息列不被牺牲
        order = sorted(range(len(headers)), key=lambda i: widths[i], reverse=True)
        while total_body > available and widths[order[0]] > 6:
            widest = order[0]
            widths[widest] -= 1
            total_body -= 1
            order.sort(key=lambda i: widths[i], reverse=True)

    lines: List[str] = []
    header_line = " ".join(
        pad(truncate(str(h), widths[i]), widths[i]) for i, h in enumerate(headers)
    )
    lines.append(Palette.paint(Palette.BOLD, header_line))
    lines.append(Palette.grey(" ".join("-" * w for w in widths)))
    for row in normalized:
        lines.append(
            " ".join(
                pad(truncate(cell, widths[i]), widths[i], align=aligns[i])
                for i, cell in enumerate(row)
            )
        )
    return "\n".join(lines)


def bar(ratio: float, width: int = 20, *, filled: str = "█", empty: str = "░") -> str:
    """渲染一个占比条形图。

    :param ratio: 0~1 的占比，超出范围会被夹住。
    """
    ratio = min(max(ratio, 0.0), 1.0)
    units = int(round(ratio * width))
    return filled * units + empty * (width - units)


def rule(title: str = "", *, char: str = "─") -> str:
    """渲染一条带可选标题的分割线。"""
    width = terminal_width()
    if not title:
        return Palette.grey(char * width)
    plain = " %s " % title
    remaining = max(0, width - _display_width(plain) - 2)
    left = remaining // 2
    right = remaining - left
    return Palette.grey(char * left) + Palette.bold(title) + Palette.grey(char * right)


def render_waterfall(rows: Sequence["object"], *, max_rows: int = 30) -> str:
    """在终端里绘制简易瀑布图。

    :param rows: :func:`harscope.analyze.HarAnalysis.waterfall` 的结果。
    :param max_rows: 最多绘制多少行。
    :returns: 多行字符串（含 ANSI 颜色时会自动适配）。
    """
    if not rows:
        return Palette.grey("（没有可用于绘制瀑布图的请求记录）")

    selected = list(rows)[:max_rows]
    total = max(row.offset_ms + row.duration_ms for row in selected) or 1.0

    label_width = 34
    timeline = max(20, terminal_width() - label_width - 22)
    lines: List[str] = []
    lines.append(rule("瀑布图 %d 行 / 总跨度 %s" % (len(selected), human_ms(total))))

    phases_seen: List[str] = []
    for row in selected:
        label = truncate("%s %s" % (row.entry.request.method, row.entry.request.display_path),
                         label_width)
        start = int(row.offset_ms / total * timeline)
        canvas = [" "] * timeline
        cursor = start
        for phase, value in row.phases:
            if phase not in phases_seen:
                phases_seen.append(phase)
            length = max(1, int(value / total * timeline)) if value else 0
            marker = _phase_marker(phase)
            for offset in range(length):
                position = min(cursor + offset, timeline - 1)
                canvas[position] = Palette.paint(_phase_color(phase), marker)
            cursor += length
            if cursor >= timeline:
                break
        lines.append(
            "%s %s %s" % (
                Palette.grey("%6.0fms" % row.offset_ms),
                Palette.bold(pad(label, label_width)),
                "".join(canvas),
            )
        )
    lines.append(rule())
    legend = "  ".join(
        Palette.paint(_phase_color(p), "■") + " %s" % PHASE_LABEL_ZH.get(p, p)
        for p in phases_seen
    )
    if legend:
        lines.append(Palette.grey("图例：") + legend)
    return "\n".join(lines)


PHASE_LABEL_ZH = {
    "blocked": "阻塞",
    "dns": "DNS",
    "connect": "TCP",
    "ssl": "TLS",
    "send": "发送",
    "wait": "首字节",
    "receive": "下载",
}


def _phase_marker(phase: str) -> str:
    """为不同分段选择不同的填充字符，便于单色终端也能区分。"""
    return {
        "blocked": "·",
        "dns": "d",
        "connect": "c",
        "ssl": "s",
        "send": ">",
        "wait": "=",
        "receive": "#",
    }.get(phase, "*")


def _phase_color(phase: str) -> str:
    """分段对应的 ANSI 颜色码。"""
    return {
        "blocked": Palette.GREY,
        "dns": Palette.BLUE,
        "connect": Palette.MAGENTA,
        "ssl": Palette.YELLOW,
        "send": Palette.GREEN,
        "wait": Palette.CYAN,
        "receive": Palette.RED,
    }.get(phase, Palette.RESET)
