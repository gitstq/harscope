"""HAR 文件/文本的容错解析器。

现实中的 HAR 至少有四种「方言」上线：Chrome DevTools、Firefox/Safari Inspector、
Charles/Fiddler 代理、以及各类自研爬虫采集器。它们共同的毛病包括：

* ``log`` 节点缺失，只有裸的 ``entries``；
* ``headersSize`` / ``bodySize`` / 时间为 ``-1``；
* ``startedDateTime`` 带 ``Z`` 或带毫秒，甚至缺失；
* ``content`` 节点整个不见；
* 顶层套了WebSocket / ``0 entries`` 的空抓取。

本模块的策略是**尽量读出来**，把结构性问题记进 :attr:`Har.warnings`，
只有连最基本形态都不满足时才抛 :class:`~harscope.exceptions.HarParserError`。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Union

from .exceptions import HarParserError
from .model import Har, HarEntry, HarPage

__all__ = ["loads", "load", "parse", "sniff"]

PathLike = Union[str, "os.PathLike[str]"]  # noqa: F821 - 仅在类型注解中使用


def loads(text: Union[str, bytes, bytearray], *, source: str = "<memory>") -> Har:
    """解析 HAR 文本。

    :param text: HAR 原始文本（``str`` / ``bytes`` 均可，自动处理 BOM）。
    :param source: 来源标识，仅用于生成更友好的错误信息。
    :raises HarParserError: JSON 非法或结构不可用。
    :returns: 填充完毕的 :class:`~harscope.model.Har`。
    """
    if isinstance(text, (bytes, bytearray)):
        raw = bytes(text)
        for bom in (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"):
            if raw.startswith(bom):
                raw = raw[len(bom):]
                break
        try:
            text = raw.decode("utf-8", "replace")
        except UnicodeDecodeError as exc:  # pragma: no cover - 防御分支
            raise HarParserError("无法按 UTF-8 解码 HAR 内容：%s" % exc) from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise HarParserError("%s 不是合法的 JSON：%s" % (source, exc)) from exc
    return parse(data, source=source)


def load(path: PathLike) -> Har:
    """从磁盘路径读取并解析 HAR 文件。

    :param path: 文件路径；``-`` 表示从标准输入读取。
    :raises HarParserError: 文件不存在或内容非法。
    """
    if str(path) == "-":
        import sys

        return loads(sys.stdin.buffer.read(), source="<stdin>")
    try:
        with open(path, "rb") as handle:
            payload = handle.read()
    except OSError as exc:
        raise HarParserError("无法读取文件 %s：%s" % (path, exc)) from exc
    return loads(payload, source=str(path))


def sniff(data: Any) -> Dict[str, Any]:
    """从任意结构里尽力取出 ``log`` 节点。

    :param data: 反序列化后的顶层对象。
    :returns: 被视为 HAR ``log`` 的 dict；找不到时返回空 dict。
    """
    if isinstance(data, dict):
        log = data.get("log")
        if isinstance(log, dict):
            return log
        # 一些采集器会把 log 内容直接平铺到顶层
        if "entries" in data or "creator" in data:
            return data
        return {}
    if isinstance(data, list):
        # 极少数资源 Only-body 变体：直接给出 entries 数组
        return {"entries": data, "version": "1.2"}
    return {}


def parse(data: Any, *, source: str = "<memory>") -> Har:
    """把反序列化的 HAR 结构转成 :class:`~harscope.model.Har`。

    :param data: JSON 反序列化结果。
    :param source: 来源标识。
    :raises HarParserError: 结构中不存在可用条目或形态完全不符。
    """
    warnings: List[str] = []
    log = sniff(data)
    if not log:
        raise HarParserError(
            "%s 不是 HAR 结构：缺少 log / entries 节点" % source, warnings
        )

    version = str(log.get("version") or "1.2")
    creator = log.get("creator") if isinstance(log.get("creator"), dict) else {}
    browser = log.get("browser") if isinstance(log.get("browser"), dict) else {}

    raw_pages = log.get("pages")
    pages: List[HarPage] = []
    if isinstance(raw_pages, list):
        for raw in raw_pages:
            if isinstance(raw, dict):
                pages.append(HarPage.from_dict(raw))
    elif raw_pages is not None:
        warnings.append("pages 节点不是数组，已忽略")

    raw_entries = log.get("entries")
    entries: List[HarEntry] = []
    if isinstance(raw_entries, list):
        for index, raw in enumerate(raw_entries):
            if not isinstance(raw, dict):
                warnings.append("第 %d 条记录不是对象，已跳过" % index)
                continue
            entries.append(HarEntry.from_dict(raw, index=index))
    else:
        warnings.append("entries 节点不是数组")

    if not entries:
        raise HarParserError(
            "%s 中没有可用的请求记录（entries 为空）" % source, warnings
        )

    missing_time = sum(1 for e in entries if not e.started_date_time)
    if missing_time == len(entries):
        warnings.append("所有记录都缺少 startedDateTime，时间轴分析会退化为累计模型")
    elif missing_time:
        warnings.append("%d/%d 条记录缺少 startedDateTime" % (missing_time, len(entries)))

    missing_transfer = sum(1 for e in entries if e.response.transfer_size is None)
    if missing_transfer:
        warnings.append(
            "%d/%d 条记录缺少 _transferSize，传输体积回退到 bodySize 估算"
            % (missing_transfer, len(entries))
        )

    har = Har(
        version=version,
        creator_name=str(creator.get("name") or ""),
        creator_version=str(creator.get("version") or ""),
        browser_name=str(browser.get("name") or ""),
        browser_version=str(browser.get("version") or ""),
        comment=str(log.get("comment") or ""),
        pages=pages,
        entries=entries,
        source=source,
        warnings=warnings,
    )
    _rebuild_missing_times(har)
    return har


def _rebuild_missing_times(har: Har) -> None:
    """为缺少 ``startedDateTime`` 的记录合成时间基准。

    策略很简单：缺失的记录紧跟其**上一条**记录的完成时间开始。
    这样在最坏情况下也只是把串行请求画成了串行，不会把整条时间轴拉长到失真。
    """
    previous = None
    for entry in har.entries:
        if entry.started_date_time is None and previous is not None:
            entry.started_date_time = _shift_ms(previous.started_date_time, previous.time_ms)
        if entry.started_date_time is not None:
            previous = entry


def _shift_ms(moment: Any, milliseconds: Union[int, float]) -> Any:
    """把某个 ``datetime`` 向后平移指定毫秒。"""
    from datetime import timedelta

    return moment + timedelta(milliseconds=float(milliseconds or 0))
