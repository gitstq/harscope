<div align="center">

# 🔬 HarScope

**零依赖的 HTTP Archive (HAR) 分析与性能取证工作台**

[![CI](https://github.com/gitstq/harscope/actions/workflows/ci.yml/badge.svg)](https://github.com/gitstq/harscope/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](#-核心特性)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

**零第三方依赖 · 纯 Python 标准库 · 离线可用 · 支持类型提示**

<br/>

🌏 **简体中文** ｜ [繁體中文](./README.zh-TW.md) ｜ [English](./README.en.md)

</div>

---

## 🎉 项目介绍

前端性能优化的第一步，永远是**看清真相**。浏览器开发者工具能给你一张漂亮的瀑布图，但它有三个硬伤：数据带不走、指标不可比、结论进不了 CI。等你想把「这次发布到底有没有变慢」变成一条流水线上的硬性门禁时，才发现手里只有一张截图。

**HarScope** 就是为了解决这个问题而生的。它把一个 **HAR（HTTP Archive 1.2）** 文件当成证据来解剖 —— 谁在拖慢首屏、哪个域名吃掉了大半带宽、哪些请求被重复发了三次、图片到底有没有真的开压缩、有没有请求把 `token` 明晃晃地写在 URL 里 —— 全部用数字说话，并且能直接生成一个**单文件 HTML 报告**丢进群里，或者变成一个**非零退出码**卡住不合格的合并请求。

最关键的取舍是：**HarScope 一行第三方依赖都没有**。没有 `requests`，没有 `pydantic`，没有 `rich`，没有 `click`。全部逻辑基于 Python 标准库实现 —— 这意味着它能被塞进任何受限的内网环境、任何 CI 镜像、任何离线工位机，装上就跑，不会有依赖冲突，也不会有供应链安全问题。它还内置了一个**纯标准库实现的 HAR 录制器**：即使手边没有浏览器、没有 DevTools，也能直接录下一个页面的完整加载过程。

> 🎯 **一句话定位**：把「我怀疑这里有点慢」变成「第 7 个请求 TTFB 331ms，占首屏耗时 42%，建议加 preconnect」。

### 🔍 它解决什么问题

| 场景 | 以前 | 用 HarScope |
| --- | --- | --- |
| 排查首屏慢 | 手动拖 DevTools，肉眼找长条 | `harscope slow app.har --by wait` 直接给 TTFB 排行 |
| 找出体积黑洞 | 逐个点开看 Size 列 | `harscope mime` 按 MIME 聚合传输体积与压缩节省 |
| 检查第三方脚本 | 记不住谁加载了谁 | `harscope domains` 按域名拆请求数、体积、错误数 |
| 上线前把控 | 「感觉还行」 | `harscope ci` 用退出码表达是否达标 |
| 给老板/客户汇报 | 截图 + 手动写文档 | `harscope report` 生成自包含 HTML，双击即开 |
| 没有浏览器环境 | 无从下手 | `harscope record <url>` 生成 HAR，隐私优先 |

---

## ✨ 核心特性

### 🧊 真正的零依赖

- 📦 **`dependencies = []`** —— 不是「依赖很少」，是**一个都没有**。
- 🔌 只用 `dataclasses` / `json` / `csv` / `http.client` / `ssl` / `html.parser` / `urllib.parse` / `zipapp` 等标准库模块。
- 🛡️ 无供应链投毒风险，内网与离线环境照样能装。
- 🏷️ 附带 `py.typed`（PEP 561），下游项目 import 时自动获得完整类型提示。

### 🧱 容错式解析：脏数据也能出结果

真实世界的 HAR 从来都不干净。改包工具会丢字段，代理会把 `_transferSize` 写成 `-1`，某些导出压根没有 `startedDateTime`。HarScope 的处理原则是**永不抛异常，尽量给数字**：

- 🧯 体积回退链：`_transferSize` → `bodySize` → `content.size` → `0`，并记录降级说明。
- ⏱️ 缺失时间戳按「紧接上一条之后」回填，保证时间轴单调且跨度不失真。
- 🔤 数值字段可能是字符串、可能是 `-1`、可能是 `null`，统一归一化后才参与计算。
- 🪧 所有降级行为不会静默吞掉 —— `summary` 底部会列出**数据质量提示**，让你知道哪些数字是估算值。

### 📊 15 个命令，一个命令回答一个问题

| 命令 | 回答的问题 |
| --- | --- |
| 🧭 `summary` | 这次会话整体健康吗？ |
| 🌊 `waterfall` | 时间到底花在哪一段？ |
| 🌐 `domains` | 哪个域名最占资源？ |
| 🧩 `mime` | 体积都被什么类型的资源吃掉了？ |
| 🐢 `slow` | 最慢的是谁？按总耗时还是按 TTFB 排？ |
| 🐘 `largest` | 最大的是谁？压缩前后差多少？ |
| 🚦 `status` | 4xx / 5xx 集中在哪些 URL？ |
| 📄 `pages` | 单页场景下的 DOMContentLoaded / onLoad 是多少？ |
| 👯 `dupes` | 有没有把同一个请求发了好几遍？浪费多少字节？ |
| 🛡️ `security` | 有没有明文传输、缺 CSP、Cookie 没加 HttpOnly？ |
| 📤 `export` | 导出 JSON / CSV / Markdown / SVG / HTML |
| 📑 `report` | 一键生成自包含 HTML 报告（同事双击就能看） |
| 🚧 `ci` | 这次改动有没有让性能倒退？ |
| 🎥 `record` | 没有浏览器，怎么生成 HAR？ |
| 🩺 `doctor` | 环境为什么不对劲？ |

### 🚧 CI 原生：用退出码说话

`harscope ci` 的退出码有明确语义，可直接接进 GitHub Actions / GitLab CI / Jenkins：

| 退出码 | 含义 |
| --- | --- |
| `0` | 全部检查通过 |
| `1` | 有指标超过阈值（不达标） |
| `2` | 输入错误或文件不可读 |

```bash
harscope ci app.har --max-requests 80 --max-transfer-kb 2048 --max-p95-ms 800 --require-https
```

![CI 输出效果](docs/images/ci.svg)

### 🎥 隐私优先的 HAR 录制器

- 🕸️ 自定义 `HTTPConnection.connect()`，实测**真实的 DNS / TCP / TLS / 发送 / 等待 / 接收**六段耗时，而非事后估算。
- 🧵 线程池并发拉取一级静态资源（默认最多 12 个），模拟浏览器的并行加载行为。
- 🔐 **默认不保存任何响应体**，只保留体积与耗时 —— 抓线上页面时不会把真实用户数据写进文件。
- 🔁 自动跟随跳转并记录每一跳，还原真实的重定向链。

### 🎨 终端可读性与呈现多样

- 🌈 自动检测 TTY 与 `NO_COLOR`，管道里自动关色，`HARSCOPE_FORCE_COLOR=1` 可强制上色。
- 📐 按**东亚宽字符宽度**算列宽，中英文混排不会错位。
- 📤 五类导出：JSON（二次处理）、CSV（Excel 透视）、Markdown（贴进 PR/Issue）、SVG（嵌文档）、HTML（自包含单文件汇报）。

---

## 🚀 快速开始

### 📋 前置要求

| 项目 | 要求 |
| --- | --- |
| Python | **>= 3.8**（已在 3.8 ~ 3.13 上验证） |
| 操作系统 | Windows / macOS / Linux，无平台相关代码 |
| 第三方依赖 | **无** |
| 磁盘空间 | 约 500 KB |

### ⚡ 三步跑起来

```bash
# ① 安装（无第三方依赖，秒完成）
pip install git+https://github.com/gitstq/harscope.git@v1.0.0

# ② 验证
harscope doctor

# ③ 看一眼示例 HAR 的体检结果
harscope summary examples/sample.har
```

<details>
<summary>📺 点开看看 <code>summary</code> 的真实输出</summary>

```
───────────────────────────────── 会话总览 ─────────────────────────────────
🔬 HAR 会话 示例商城 · 首页
· 请求 14 条 ｜ 域名 5 个 ｜ HAR 1.2 ｜ 采集器 HarScope Fixture 1.0

会话跨度     592 ms             累计耗时     1.12 s
并发度       1.89×              平均耗时     80.0 ms
P50          59.6 ms            P95          193 ms
平均 TTFB    42.8 ms            总传输       1.4 MB
响应体       1.4 MB             头部         5.6 KB（0.4%）
解压体积     1.9 MB             压缩节省     528 KB（27.1%）
HTTPS        92.9%              缓存命中     7.1%

状态码分布
  2xx ██████████████████████░░░░░░      11 78.6%
  3xx ██░░░░░░░░░░░░░░░░░░░░░░░░░░       1  7.1%
  4xx ██░░░░░░░░░░░░░░░░░░░░░░░░░░       1  7.1%
  5xx ██░░░░░░░░░░░░░░░░░░░░░░░░░░       1  7.1%

域名 TOP10
域名                   请求数 传输体积 占比               平均耗时 错误
---------------------- ------ -------- ------------------ -------- ----
files.example.com           1   1.0 MB █████████████░░░░░   332 ms
cdn.example.com             7   370 KB █████░░░░░░░░░░░░░  67.3 ms    1
shop.example.com            3  24.3 KB ░░░░░░░░░░░░░░░░░░  46.0 ms
api.example.com             2   5.2 KB ░░░░░░░░░░░░░░░░░░  61.6 ms    1
thirdparty.example.com      1    265 B ░░░░░░░░░░░░░░░░░░  55.7 ms

⚠️  数据质量提示
  - 1/14 条记录缺少 startedDateTime
  - 1/14 条记录缺少 _transferSize，传输体积回退到 bodySize 估算
```

</details>

### 🎥 从零生成一份 HAR

没有现成的抓包文件？直接从 URL 录一份：

```bash
harscope record https://example.com -o trace.har
harscope waterfall trace.har
harscope report trace.har -o report.html
```

### 🧪 免安装体验

```bash
git clone https://github.com/gitstq/harscope.git
cd harscope
PYTHONPATH=src python -m harscope summary examples/sample.har
```

---

## 📖 详细使用指南

### 🧭 1. 会话总览 `summary`

```bash
harscope summary app.har              # 人类可读报表
harscope summary app.har --json       # 结构化输出，便于管道处理
harscope summary app.har --top 20     # 域名/MIME 排行放宽到 20 行
```

**关注读法**：`并发度` 越接近 1 说明请求几乎串成了一条链，通常意味着能做资源提示（`preconnect` / `preload`）并联起来；`压缩节省` 低于 50% 就该回去查文本资源有没有开 Brotli / gzip；`头部` 占比超过 5% 往往是 Cookie 失控的信号。

### 🌊 2. 瀑布图 `waterfall`

```bash
harscope waterfall app.har            # 默认展示最慢的 30 条
harscope waterfall app.har --top 60
```

七色分段，一眼看清时间花在哪：

| 颜色 | 阶段 | 含义 |
| --- | --- | --- |
| 🟪 紫 | Blocked | 排队等待连接 |
| 🟫 棕 | DNS | 域名解析 |
| 🟧 橙 | Connect | TCP 握手 |
| 🟨 黄 | TLS | TLS 握手 |
| 🟦 蓝 | Send | 发送请求 |
| 🟩 绿 | Wait | 等待首字节（TTFB） |
| 🟪 靛 | Receive | 接收响应体 |

> 💡 绿色（Wait）特别长 → 服务端问题；橙色/黄色特别长 → 连接复用没做好，考虑 `preconnect`；靛色（Receive）特别长 → 资源太大或带宽受限。

### 🌐 3. 域名视角 `domains`

```bash
harscope domains app.har --top 20
```

一眼揪出第三方脚本大户。「安全」列亮红的表示该域名存在明文 HTTP 请求。

### 🧩 4. 资源类型视角 `mime`

```bash
harscope mime app.har
```

同时给出**传输体积**、**解压体积**与**压缩节省率**。若某个 `application/javascript` 的节省率是 0%，那就是忘了开压缩。

### 🐢 5. 慢请求排行 `slow`

```bash
harscope slow app.har --top 10               # 按总耗时
harscope slow app.har --top 10 --by wait     # 按 TTFB（直击后端慢的根因）
```

> 🎯 `--by wait` 是最容易被忽略但最有价值的参数。总耗时慢常常是资源太大（好解决），TTFB 慢才是真的后端有事。

### 🐘 6. 大资源排行 `largest`

```bash
harscope largest app.har --top 10
```

### 🚦 7. 状态码 `status`

```bash
harscope status app.har
harscope status app.har --json | jq '.errors'
```

### 📄 8. 页面维度 `pages`

```bash
harscope pages app.har
```

适用于 DevTools 导出的含 `pages` 节点的 HAR，给出每个页面的请求数、传输体积、跨度、`DOMContentLoaded` 与 `onLoad`。

### 👯 9. 重复请求 `dupes`

```bash
harscope dupes app.har
```

识别**同方法 + 同 URL** 的完全重复请求，并给出去重后可节省的字节数。这是投入产出比最高的一档优化。

### 🛡️ 10. 安全与合规审计 `security`

```bash
harscope security app.har
harscope security app.har --fail-on high      # 存在高危发现时退出码为 1
```

四类检查，输出 A~E 分级评分：

| 类别 | 检查内容 |
| --- | --- |
| 🔐 传输安全 | 明文 HTTP、混合内容、HTTP→HTTPS 重定向 |
| 🧱 响应头合规 | HSTS / CSP / X-Content-Type-Options / Referrer-Policy / X-Frame-Options / Permissions-Policy 等是否缺失 |
| 🍪 Cookie 属性 | `Secure` / `HttpOnly` / `SameSite` 是否设置 |
| 🕵️ 信息泄露 | URL 或请求头里出现 `token` / `password` / `secret` / `api_key` 等敏感参数、响应头暴露服务器版本号 |

**评分模型**（满分 100）：传输安全 30 分 + 响应头合规 30 分 + 安全发现 40 分。刻意保留的高危项（混合内容、凭证写进 URL）会让评分直接掉到 E 级，便于演示门禁效果。

### 📤 11. 多格式导出 `export`

```bash
harscope export app.har --format json     -o report.json   --entries
harscope export app.har --format csv      -o entries.csv             # 带 BOM，Excel 直接双击不乱码
harscope export app.har --format markdown -o report.md
harscope export app.har --format svg      -o waterfall.svg
harscope export app.har --format html     -o report.html
harscope export app.har --format html     -o report.html --no-security --force
```

| 格式 | 适合拿去做什么 |
| --- | --- |
| `json` | 二次处理、入库、喂给 Prometheus / 自建看板 |
| `csv` | 丢进 Excel 做透视表、给非技术同事看明细 |
| `markdown` | 直接贴进 PR、Issue、周报 |
| `svg` | 嵌进 Confluence / Notion / Wiki 文档 |
| `html` | 自包含单文件（内联样式与 SVG），邮件发送或直接双击打开 |

### 🚧 12. CI 质量门禁 `ci`

```bash
harscope ci app.har \
  --max-requests 80 \
  --max-transfer-kb 2048 \
  --max-load-ms 5000 \
  --max-p95-ms 800 \
  --min-cache-ratio 0.3 \
  --max-duplicate-requests 2 \
  --require-https \
  --require-security-headers \
  --max-findings 5
```

全部参数都是可选的 —— 只填你真正关心的那几项，其余不检查。每条不达标项都会附上**具体优化建议**，而不是只丢一个「失败」。

<details>
<summary>🔧 GitHub Actions 集成示例（复制即用）</summary>

```yaml
name: Performance Gate
on: [pull_request]

jobs:
  harscope:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      # 零依赖，安装极快，无需缓存
      - run: pip install git+https://github.com/gitstq/harscope.git@v1.0.0

      # 录制被测页面（无头环境也能用）
      - run: harscope record https://staging.example.com -o trace.har --assets 20

      # 门禁：不达标即以非零码失败，阻断合并
      - run: harscope ci trace.har --max-requests 80 --max-transfer-kb 2048 --max-p95-ms 800 --require-https

      # 无论通过与否都保留报告
      - if: always()
        run: harscope report trace.har -o harscope-report.html --force
      - if: always()
        uses: actions/upload-artifact@v4
        with:
          name: harscope-report
          path: harscope-report.html
```

</details>

### 🎥 13. 录制 HAR `record`

```bash
harscope record https://example.com -o trace.har
harscope record https://example.com -o trace.har --assets 20 --timeout 15
harscope record https://example.com -o trace.har --cross-host          # 允许抓取 CDN 等跨域资源
harscope record https://example.com -o trace.har --header "Cookie: k=v"
harscope record https://internal.test -o trace.har --insecure          # 自签证书环境
```

> 🔐 **隐私说明**：录制时**只记录 URL、请求头、响应头、体积与耗时，不落盘任何响应体内容**，可直接用于对公网页面的巡检。

### 🩺 14. 环境自检 `doctor`

```bash
harscope doctor
harscope doctor --json
```

输出 Python 版本、平台、OpenSSL 版本、终端着色状态，快速定位「为什么颜色没了 / 为什么 TLS 握手失败」。

### 🐍 15. 作为 Python 库集成

HarScope 不只是一个命令行工具，它同样是一套可以直接嵌入自有平台的分析库。

```python
from harscope import load, loads, analyze

# 从文件加载
har = load("app.har")

# 也可以直接从字符串 / 字节加载
har = loads(open("app.har", encoding="utf-8").read())

analysis = analyze(har)

print(f"请求数: {analysis.total_requests}")
print(f"域名数: {analysis.unique_hosts}")
print(f"会话跨度: {analysis.duration_ms:.1f} ms")
print(f"P95: {analysis.p95_ms:.1f} ms")
print(f"传输体积: {analysis.transfer_bytes} bytes")
print(f"压缩节省: {analysis.compression_saving_ratio:.1%}")
print(f"HTTPS 占比: {analysis.https_ratio:.1%}")
print(f"并发度: {analysis.parallelism:.2f}x")

# 一次性拿到全部摘要（dict，可直接 json.dumps）
summary = analysis.summary_dict()
```

**逐可用指标一览：**

| 属性 / 方法 | 返回 | 说明 |
| --- | --- | --- |
| `analysis.total_requests` | `int` | 请求总条数 |
| `analysis.unique_hosts` / `hosts` | `int` / `Set[str]` | 去重后的域名 |
| `analysis.duration_ms` | `float` | 会话跨度（最早开始到最晚结束） |
| `analysis.total_time_ms` | `float` | 所有请求耗时之和 |
| `analysis.parallelism` | `float` | 并发度 = 累计耗时 / 会话跨度 |
| `analysis.average_ms` / `p50_ms` / `p95_ms` / `p99_ms` | `float` | 分位数（线性插值） |
| `analysis.average_wait_ms` / `p95_wait_ms` | `float` | TTFB 相关统计 |
| `analysis.transfer_bytes` / `body_transfer_bytes` / `header_bytes` | `int` | 体积拆解 |
| `analysis.uncompressed_body_bytes` | `int` | 解压后响应体总量 |
| `analysis.compression_saving_bytes` / `_ratio` | `int` / `float` | 压缩收益 |
| `analysis.https_ratio` / `cache_hit_ratio` / `success_ratio` | `float` | 比例类指标 |
| `analysis.insecure_requests` | `int` | 明文 HTTP 请求数 |
| `analysis.status_classes` / `status_codes` | `Dict` | 状态码聚合 |
| `analysis.error_entries` / `client_error_entries` | `List[HarEntry]` | 失败请求明细 |
| `analysis.domain_stats(n)` | `List[DomainStat]` | 域名维度聚合 |
| `analysis.mime_stats(n)` | `List[MimeStat]` | MIME 维度聚合 |
| `analysis.duplicates(top=n)` | `List[DuplicateGroup]` | 重复请求分组 |
| `analysis.redirect_chains()` | `List[List[HarEntry]]` | 重定向链还原 |
| `analysis.waterfall(limit=n)` | `List[WaterfallRow]` | 瀑布图数据 |
| `analysis.page_stats()` | `List[PageStat]` | 页面维度聚合 |
| `analysis.slowest(n, by="time"\|"wait")` | `List[HarEntry]` | 慢请求排行 |
| `analysis.largest(n)` | `List[HarEntry]` | 大资源排行 |
| `analysis.summary_dict()` | `Dict[str, Any]` | 全部核心指标打包成 dict |

**导出器与安全审计也可单独调用：**

```python
from harscope import load, analyze
from harscope.exporters import to_json, to_markdown, to_csv, to_svg_waterfall, to_html_report
from harscope.security import audit

har = load("app.har")
analysis = analyze(har)
sec = audit(har)

print(f"安全评分: {sec.score}/100 ({sec.grade} 级)")
for f in sec.findings:
    print(f"[{f.severity}] {f.category}: {f.message}")

# 生成各类产物
html = to_html_report(analysis, audit=sec, waterfall_limit=40)
open("report.html", "w", encoding="utf-8").write(html)

open("report.md", "w", encoding="utf-8").write(to_markdown(analysis, audit=sec))
open("entries.csv", "w", encoding="utf-8").write(to_csv(analysis.entries))
open("waterfall.svg", "w", encoding="utf-8").write(to_svg_waterfall(analysis, limit=40))
```

**在自己的代码里复用录制器：**

```python
from harscope.recorder import record, RecordOptions

options = RecordOptions(
    timeout=15.0,
    max_assets=20,
    max_redirects=5,
    same_host_only=True,
    headers={"Cookie": "session=abc"},
)
har_dict = record("https://example.com", options)   # 返回标准 HAR dict

import json
json.dump(har_dict, open("trace.har", "w"), ensure_ascii=False, indent=2)
```

**错误处理：**

```python
from harscope import load, analyze
from harscope.exceptions import (
    HarScopeError, HarParserError, NetworkRecordError, ExportError,
)

try:
    analysis = analyze(load("app.har"))
except HarParserError as exc:
    print(f"HAR 解析失败：{exc}")
    for warning in exc.warnings:
        print(f"  警告：{warning}")
except HarScopeError as exc:
    print(f"HarScope 错误：{exc}")
```

> 🧯 `HarParserError` 会把**非致命问题**收集到 `exc.warnings` 里，而不是直接崩掉 —— 这在批量扫描成百上千份 HAR 时尤其重要。

### 🔤 通用参数

| 参数 | 作用 |
| --- | --- |
| `--json` | 以 JSON 输出结构化结果，配合 `jq` 使用 |
| `--no-color` | 关闭 ANSI 颜色（等价于 `NO_COLOR=1`） |
| `--version` | 打印版本号 |
| `-h` / `--help` | 查看帮助 |

**环境变量：**

| 变量 | 作用 |
| --- | --- |
| `NO_COLOR=1` | 关闭终端着色 |
| `HARSCOPE_FORCE_COLOR=1` | 管道重定向时仍然强制着色 |

---

## 💡 设计思路与迭代规划

### 🧠 为什么坚持零依赖

这是整个项目最核心、也是最「反直觉」的一次取舍。

**代价**：放弃了 `requests`（TLS 细节要自己处理）、`pydantic`（数据校验得手写）、`rich`（终端渲染得自己算列宽）、`click`（ argparse 写到手酸）。代码量大概多了 30%。

**收益**：

1. **可移植到任何地方** —— 离线工位机、断网内网、体积受限的 CI 镜像、`python:alpine` 容器，装上就能跑。
2. **供应链攻击面为零** —— 没有 transitive dependency，不存在某个间接依赖被投毒的风险。对一个**会被放进 CI、能读到真实 HAR 数据**的工具来说，这一点的重要性远超省下的那些代码。
3. **安装耗时接近零** —— `pip install` 不需要解析依赖树，在流水线里就是干净利落的一步。
4. **不会因为依赖版本打架** —— 不需要担心某个下游项目要求的 `pydantic<2` 跟 HarScope 冲突。

判断标准很简单：**这东西要在别人的 CI 里跑。** 一个 CI 工具的依赖，就是所有人的技术债。

### 🧱 为什么是「先容错，再计算」

HAR 是**由工具写给工具看的交换格式**，而写它的工具有几十种，质量参差不齐。如果采用严格解析：

- 遇到 `_transferSize: -1` 就报错 → 用户会说「用不了」，而不是感谢你严谨；
- 遇到缺少 `startedDateTime` 就跳过整条 → 统计口径会悄悄失真，用户却毫不知情。

HarScope 的折中是：**解析时尽量给值，但同时把降级行为明确记进 `notes`，并在 `summary` 底部展示出来。** 数字可以是估算的，但用户必须知道它是估算的 —— 这是「取证」类工具的底线。

### ⏱️ 时间轴回填的一个真实教训

第一版在回填缺失时间戳时，把「之前所有条目的耗时」累加到了缺失条目上，导致会话跨度从真实的 447 ms 被放大到 1467 ms，并发度也从 1.49× 虚高到 2.57× —— 一个看起来「不太好但能忍」的结果，实际上是完全错误的。修正为「紧接上一条之后开始」后，指标立刻回到合理区间。

这件事说明：**性能工具的 bug 不会表现为崩溃，只会表现为一个你还挺相信的错误数字。** 因此项目里所有与时间、体积相关的指标都有对应的单元测试做量级断言。

### 📐 安全评分为什么不直接扣分

最初的评分是「发现问题就扣分」，结果示例 HAR 直接被扣到 0 分 E 级 —— 因为发现了混合内容和 URL 里的凭证。这看起来像「你这个站很烂」，但其实传达不了任何可行动的信息：到底哪里最该先修？

改成分段加权后就好读多了：**传输安全 30 分 + 响应头合规 30 分 + 安全发现 40 分**。即使某个站点有高危发现，只要传输和安全响应头做得好，仍能拿到 C 级 —— **评分表达的是「整体安全姿态」，而具体的 actionable 项交给 `findings` 清单逐条列出。** 评分给管理者看，清单给工程师看。

### 🗺️ 迭代路线图

| 版本 | 计划内容 | 状态 |
| --- | --- | --- |
| **v1.0.0** | 15 个命令、5 类导出、内置录制器、126 个单元测试、三语文档 | ✅ 已发布 |
| v1.1.0 | HAR 文件差异对比（`harscope diff A.har B.har`）、指标回归趋势 | 📋 计划中 |
| v1.2.0 | Core Web Vitals 近似估算（LCP / FID / CLS 的 HAR 侧推算） | 📋 计划中 |
| v1.3.0 | JSON Schema 级别的 HAR 校验报告、`--strict` 严格模式 | 💡 构思中 |
| v2.0.0 | Prometheus Exporter 与 Grafana 面板模板、Webhook 告警 | 💡 构思中 |

**明确不做的**：引入第三方依赖、内置浏览器自动化、把 HAR 上传云端解析、支持 HTTP/3 专有指标（依赖服务端暴露，HAR 层面无法可靠获取）。

---

## 📦 打包与部署指南

HarScope 属于**工具类 / 库类项目**，因此**不发布平台专属安装包**，而是提供四种灵活的获取方式。

### 🐍 方式一：pip 安装（推荐）

```bash
# 安装指定版本
pip install git+https://github.com/gitstq/harscope.git@v1.0.0

# 升级到最新 main
pip install --upgrade git+https://github.com/gitstq/harscope.git

# 从源码安装
git clone https://github.com/gitstq/harscope.git && cd harscope
pip install --no-deps .

# 可编辑模式（开发用）
pip install --no-deps -e .
```

安装后获得全局命令 `harscope`，另有等价写法 `python -m harscope`。

### 📀 方式二：构建分发包

```bash
make wheel                     # 产出 dist/harscope-1.0.0-py3-none-any.whl
python -m build                # 同时产出 wheel 与 sdist
pip install dist/*.whl         # 验证 wheel 可安装
```

产出的 wheel 是 `py3-none-any` —— 单 Wheel 通吃全部平台与 Python 版本。

### 🧳 方式三：zipapp 单文件（无安装、便携）

```bash
make zipapp                    # 产出 dist/harscope.pyz
python dist/harscope.pyz summary app.har          # 直接用
python3.11 dist/harscope.pyz waterfall app.har    # 也可以指定解释器
```

`.pyz` 是一个把整个包塞进去的可执行 zip —— **拷给别人只需发一个文件**，对方只要有 Python 就能跑。

### 🏃 方式四：完全免安装运行

```bash
git clone https://github.com/gitstq/harscope.git && cd harscope
PYTHONPATH=src python3 -m harscope summary examples/sample.har
# 或用封装脚本
bash scripts/run.sh summary examples/sample.har
```

### 🧪 本地开发与测试

```bash
make install         # 安装到当前环境
make dev             # 可编辑模式安装
make test            # 运行 126 个单元测试
make test-net        # 含网络录制器的测试
make smoke           # CLI 冒烟测试
make clean           # 清理构建产物
```

### 🔁 在 CI 中的部署方式

零依赖意味着 CI 集成极简 —— 不需要缓存依赖、不需要虚拟环境预热：

```yaml
- run: pip install git+https://github.com/gitstq/harscope.git@v1.0.0
- run: harscope ci trace.har --max-requests 80 --require-https
```

详见上文「🚧 CI 质量门禁」中的完整 Actions 示例。

### 📁 项目结构

```
harscope/
├── src/harscope/
│   ├── __init__.py       # 包入口，导出 load / loads / analyze
│   ├── __main__.py       # python -m harscope 入口
│   ├── model.py          # HAR 1.2 数据模型（容错、可空）
│   ├── parser.py         # 解析与时间轴回填
│   ├── analyze.py        # 指标聚合（P50/P95/P99、域名/MIME/瀑布图）
│   ├── security.py       # 安全与合规审计
│   ├── exporters.py      # JSON / CSV / Markdown / SVG / HTML 导出
│   ├── recorder.py       # 纯标准库 HAR 录制器
│   ├── render.py         # 终端渲染（配色、表格、瀑布图）
│   ├── cli.py            # 命令行：15 个子命令
│   ├── exceptions.py     # 异常层次
│   └── py.typed          # PEP 561 类型标记
├── tests/                # 126 个单元测试（仅用标准库 unittest）
├── examples/sample.har   # 示例 HAR 文件
├── scripts/              # run / build / test 一键脚本
├── .github/workflows/    # CI（3 系统 × 6 Python 版本）
├── pyproject.toml        # PEP 517/518 打包元数据
├── Makefile
├── CONTRIBUTING.md
├── CHANGELOG.md
└── LICENSE
```

---

## 🤝 贡献指南

欢迎 Star ⭐、Issue 🐛 与 Pull Request 🔧。完整规范见 [CONTRIBUTING.md](./CONTRIBUTING.md)，要点如下：

### 🔧 快速上手

```bash
git clone https://github.com/gitstq/harscope.git
cd harscope
pip install --no-deps -e .
make test                    # 必须全绿
```

### 🧾 Angular 提交规范

提交信息必须遵循 `<type>(<scope>): <subject>`，这是合并的前置条件：

```
feat(analyze): 新增 P99 耗时分位数指标
fix(parser): 修复缺失 startedDateTime 时时间轴回填越界
docs(readme): 补充繁体中文使用示例
refactor(security): 评分改为三段加权模型
test(cli): 覆盖 ci 命令所有阈值分支
```

允许的 type：`feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci` `chore` `revert`。

### 🚫 项目红线

- ❌ **禁止引入任何第三方运行时依赖** —— 这是项目立身之本。
- ❌ 禁止降低 Python 兼容下界（当前 `>=3.8`）。
- ❌ 禁止删除或弱化既有测试断言。
- ❌ 禁止把响应体内容写进输出或导出文件。
- ❌ 修改功能时必须**同步更新三份 README**（简中 / 繁中 / English）。

### 🐛 提交 Issue 请注意

请勿直接粘贴包含 Cookie、Authorization 或真实用户数据的 HAR 原文。请先用 `harscope export --format json` 导出聚合结果，或手工脱敏后再附最小复现片段。

---

## 📄 开源协议说明

本项目基于 **[MIT License](./LICENSE)** 开源，这意味着你可以：

- ✅ 自由使用、复制、修改、合并、发布、分发、再授权、售卖副本，**无论是商业还是非商业用途**；
- ✅ 用于闭源商业产品；
- ✅ 无需支付任何费用。

**唯一要求**：在所有副本或实质性部分中保留版权声明与许可声明。

**免责声明**：本软件按「原样」提供，不含任何明示或暗示的担保，包括但不限于适销性、特定用途适用性与非侵权性的担保。作者或版权持有人对任何索赔、损害或其他责任概不负责。

完整的法律文本见 [LICENSE](./LICENSE)。

---

<div align="center">

**如果 HarScope 帮你找到了那个偷偷拖慢首屏的请求，给个 ⭐ 吧 —— 这是零依赖项目继续走下去的唯一燃料。**

[⬆ 回到顶部](#-harscope) ｜ [提 Issue](https://github.com/gitstq/harscope/issues) ｜ [贡献指南](./CONTRIBUTING.md)

🌏 **简体中文** ｜ [繁體中文](./README.zh-TW.md) ｜ [English](./README.en.md)

</div>
