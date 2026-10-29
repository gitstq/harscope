"""HarScope —— 零依赖的 HTTP Archive (HAR) 分析与性能取证工作台。

Package layout
--------------
``model``      对 HAR 1.2 记录的纯数据建模（容错、可空）
``parser``     把任意 HAR JSON 解析成 :class:`~harscope.model.Har`
``analyze``    请求/性能指标聚合统计
``security``   传输安全、响应头与 Cookie 合规审计
``exporters``  JSON / CSV / Markdown / SVG / HTML 导出
``recorder``   纯标准库实现的 HAR 录制器（无需浏览器即可生成跟踪文件）
``render``     终端渲染辅助（配色、表格、进度条）
``cli``        命令行入口

整个包只依赖 Python 标准库，无第三方依赖。
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "HarScope Contributors"
__license__ = "MIT"

__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "Har",
    "HarEntry",
    "HarParserError",
    "load",
    "loads",
    "analyze",
]

from .exceptions import HarParserError  # noqa: E402
from .model import Har, HarEntry, HarPage  # noqa: E402
from .parser import load, loads  # noqa: E402
from .analyze import analyze  # noqa: E402

# 便捷 API：``harscope.load(path)`` / ``harscope.loads(text)`` 直接可用。
# 延迟导入可避免循环依赖，并让 ``import harscope`` 的成本降到最低。
