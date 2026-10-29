"""HarScope 自定义异常层级。

所有对外抛出的异常都继承自 :class:`HarScopeError`，方便调用方统一捕获::

    try:
        har = harscope.load("trace.har")
    except harscope.HarScopeError as exc:
        print(exc)
"""

from __future__ import annotations

from typing import Sequence


class HarScopeError(Exception):
    """所有 HarScope 异常的基类。"""


class HarParserError(HarScopeError):
    """输入的 HAR 结构非法或缺少必需字段。

    :param message: 面向用户的错误摘要。
    :param warnings: 解析过程中收集到的非致命警告，帮助定位问题。
    """

    def __init__(self, message: str, warnings: Sequence[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.warnings: Sequence[str] = tuple(warnings or ())

    def __str__(self) -> str:  # pragma: no cover - 表现层细节
        if not self.warnings:
            return self.message
        joined = "; ".join(self.warnings[:5])
        suffix = " …等 %d 条" % (len(self.warnings) - 5) if len(self.warnings) > 5 else ""
        return "%s（附加信息：%s%s）" % (self.message, joined, suffix)


class NetworkRecordError(HarScopeError):
    """HAR 录制器 ``harscope record`` 在抓取过程中失败。"""


class ExportError(HarScopeError):
    """导出/写文件失败（路径不可写、格式不支持等）。"""
