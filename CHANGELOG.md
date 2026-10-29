# 📜 变更日志

本文件记录 HarScope 的每个版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)（`MAJOR.MINOR.PATCH`）。

---

## [1.0.0] — 2026-10-30

首个正式版本。HarScope 是一个**零第三方依赖**的 HTTP Archive (HAR) 分析与性能取证工作台，
从 HAR 1.2 文件中提取瀑布图、体积归因、重复请求、安全合规等指标，并提供终端、Markdown、
CSV、JSON、SVG 与自包含 HTML 六种呈现方式，外加一个纯标准库实现的 HAR 录制器。

### ✨ 新增

**核心库**
- `harscope.load()` / `harscope.loads()`：容错解析 HAR 1.2，自动剥离 BOM，兼容 HTTP/1.1 与 HTTP/2 记录。
- `harscope.analyze()`：一次性产出 30+ 项聚合指标（P50/P95/P99、TTFB、并发度、压缩节省、缓存命中率等）。
- `harscope.model`：对 HAR 任一节点做可空建模，`-1` / 缺失 / 类型错误统一归一化为 `None`，不抛异常。
- `harscope.exporters`：JSON / CSV（带 BOM）/ Markdown / SVG 瀑布图 / 自包含 HTML 报告五类导出。
- `harscope.security`：传输安全、响应头合规、Cookie 属性、敏感信息泄露四类审计，输出 A~E 分级评分。

**命令行（15 个子命令）**
- `summary` 会话总览 · `waterfall` 终端瀑布图 · `domains` 域名分布 · `mime` 资源类型分布
- `slow` 慢请求排行 · `largest` 大资源排行 · `status` 状态码分布 · `pages` 页面维度聚合
- `dupes` 重复请求 · `security` 安全审计 · `export` 多格式导出 · `report` HTML 报告
- `ci` 质量门禁（退出码 0/1/2） · `record` 网页录制 · `doctor` 环境自检

**录制器**
- 纯标准库实现，`http.client` 打点获取真实 DNS / TCP / TLS / 发送 / 等待 / 接收六段耗时。
- 线程池并发拉取一级静态资源，模拟浏览器加载行为。
- **默认不落盘任何响应体**，只保留体积与时间，做到隐私优先。

**工程化**
- PEP 517/518 `pyproject.toml`，`[project.scripts]` 提供 `harscope` 命令。
- 内含 `py.typed`（PEP 561），下游可获得完整类型提示。
- `scripts/{run,build,test}.sh` 与 `Makefile` 提供跨平台一键运行／构建／测试。
- GitHub Actions 覆盖 6 个 Python 版本 × 3 个操作系统，共 18 个测试组合。
- 126 个单元测试，全部仅依赖标准库 `unittest`。

### 🐛 修复

- 修复缺失 `startedDateTime` 时时间轴回填逻辑把先前所有条目耗时累计叠加，导致会话跨度被高估约 3 倍的问题。
- 修复 `--fail-on` 判定倒挂：原先任一低危发现都会触发失败，现按阈值等级严格截断。
- 修复终端卡片在中英文混排下因未计算东亚宽字符宽度而列错位的问题。
- 修复安全评分被罚到 0 分的问题，改为传输 30 / 响应头 30 / 发现 40 的分段加权模型。

### 📖 文档

- 提供简体中文、繁体中文、English 三份 README，顶部带语言互跳链接。
- 提供 `CONTRIBUTING.md` 贡献指南模板，含完整 Angular 提交规范。

---

## 已发布概览

| 版本 | 发布日期 | 关键变化 |
| --- | --- | --- |
| [1.0.0] | 2026-10-30 | 首个正式版本：15 个子命令、5 类导出、内置录制器、零依赖 |

[1.0.0]: https://github.com/gitstq/harscope/releases/tag/v1.0.0
