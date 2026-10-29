# 🤝 贡献指南

感谢你愿意为 **HarScope** 出力。这份文档说明如何参与开发、提交代码与提出问题。
项目遵循 MIT 协议，任何人都可以自由使用、修改与分发。

---

## 📌 参与方式一览

| 方式 | 适用场景 | 入口 |
| --- | --- | --- |
| 🐛 报告缺陷 | 解析报错、指标异常、终端渲染错位 | [提交 Issue](https://github.com/gitstq/harscope/issues) |
| 💡 提出需求 | 想要新的指标、导出格式或命令 | [Discussions / Issue](https://github.com/gitstq/harscope/issues) |
| 📖 改进文档 | README 翻译、示例补充、错别字 | 直接提 Pull Request |
| 🔧 提交代码 | 修复缺陷、实现新命令或新导出格式 | 见下方「 Pull Request 流程 」 |

> ⚠️ 提交 Issue 时**请勿粘贴包含 Cookie、Authorization、Token 或真实用户数据的 HAR 原文**。
> 请先用 `harscope export` 导出聚合结果，或手工脱敏后再附上最小复现片段。

---

## 🧭 Pull Request 流程

1. **Fork** 本仓库并新建分支，分支名建议：
   - `feature/<短描述>`（新功能）
   - `fix/<短描述>`（缺陷修复）
   - `docs/<短描述>`（文档）
   - `refactor/<短描述>`（重构）
2. **本地开发**，务必满足下面的「红线」。
3. **补测试**：任何行为变更都应能在 `tests/` 中复现。
4. **跑全量自检**：
   ```bash
   make test                 # 单元测试
   HARSCOPE_TEST_NETWORK=1 python -m unittest discover -s tests -v
   bash scripts/test.sh      # CLI 冒烟
   ```
5. **提交**，提交信息必须使用 Angular 规范（见下）。
6. **发 PR**，在描述中说明动机、改动点与验证方式。

---

## 🧾 Angular 提交信息规范

格式：`<type>(<scope>): <subject>`，例如：

```
feat(analyze): 新增 p99 耗时分位数指标
fix(parser): 修复缺失 startedDateTime 时时间轴回填越界
docs(readme): 补充繁体中文使用示例
refactor(security): 评分改为传输/响应头/发现三段加权
test(cli): 覆盖 ci 命令的所有阈值分支
chore(build): 升级 actions/checkout 到 v4
perf(exporters): CSV 导出改为流式写入
style(render): 统一表格列宽计算
ci(workflow): 增加 Python 3.13 矩阵
build(pyproject): 收紧 requires-python 下界
revert: 回滚 "feat(cli): ..."
```

允许的 `<type>`：

| type | 含义 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 仅文档调整 |
| `style` | 格式／空格／标点，不影响逻辑 |
| `refactor` | 重构，不新增能力也不修缺陷 |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `build` | 构建系统与依赖调整 |
| `ci` | CI 配置调整 |
| `chore` | 其他杂项 |
| `revert` | 回滚历史提交 |

规则：
- `subject` 使用**祈使句、现在时**，句末不加句号；
- 一行不超过 **72 个字符**；
- 破坏性变更需正文以 `BREAKING CHANGE:` 开头说明。

---

## 🚫 项目红线（PR 会被直接拒绝）

- ❌ 引入**任何第三方运行时依赖**。HarScope 的核心卖点是「零依赖、离线可用」。
- ❌ 降低 Python 兼容下界（当前 `>=3.8`）。
- ❌ 删除或弱化 `tests/` 中的既有断言。
- ❌ 在终端输出、日志或导出文件里写入未经脱敏的请求体内容。
- ❌ 让大 HAR 文件的处理复杂度退化到无法在 1 秒内完成 10 万条请求。

---

## 🧪 开发约定

- 代码风格：**4 空格缩进**，行长上限 **120**，中文注释写在需要解释「为什么」的地方。
- 类型标注：公开函数必须带类型标注，模块顶部统一 `from __future__ import annotations`。
- 容错優先：所有来自 HAR 的字段都应假设「可能缺失、可能是 -1、可能是字符串」。
- 导出格式新增时需同时补：`.github/workflows/ci.yml` 冒烟步骤 + `tests/test_exporters.py` 断言。
- 终端渲染改动需同时验证「中文宽字符」与「无颜色（`NO_COLOR=1`）」两种模式。

---

## 🌍 文档语言

README 提供简体中文、繁体中文与 English 三语版本。修改功能后请**同步三份文档**：

- `README.md`（简体中文）
- `README.zh-TW.md`（繁体中文）
- `README.en.md`（English）

---

## 📄 行为准则

请保持友善与专业。讨论技术问题时对事不对人，不接受人身攻击、歧视性言论与垃圾推广。

---

## 🧾 许可证

你提交的代码默认以本项目采用的 [MIT License](./LICENSE) 授权发布。
