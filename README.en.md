<div align="center">

# 🔬 HarScope

**A zero-dependency HTTP Archive (HAR) analysis and performance forensics workbench**

[![CI](https://github.com/gitstq/harscope/actions/workflows/ci.yml/badge.svg)](https://github.com/gitstq/harscope/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](#-key-features)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

**Zero third-party dependencies · Pure Python standard library · Fully offline · Typed**

<br/>

🌏 [简体中文](./README.md) ｜ [繁體中文](./README.zh-TW.md) ｜ **English**

</div>

---

## 🎉 Project Intro

The first step in any frontend performance work is always the same: **see what's actually happening**. Your browser's devtools will happily draw you a beautiful waterfall chart, but it has three hard limits — the data can't leave your machine, the metrics can't be compared across runs, and the conclusions can't reach your CI. The moment you try to turn "did this release make things slower?" into a gate in your pipeline, you realize all you have is a screenshot.

**HarScope** exists to close that gap. It takes a **HAR (HTTP Archive 1.2)** file and treats it as evidence: who is blocking first paint, which origin is eating most of your bandwidth, which request is fired three times, whether your images are genuinely compressed, whether some call is shipping `token=...` in plain sight inside the URL. Every answer comes back as a number, and those numbers can become **a single self-contained HTML report** you paste into Slack or **a non-zero exit code** that blocks a failing pull request.

The defining trade-off is this: **HarScope has zero third-party dependencies.** Not `requests`, not `pydantic`, not `rich`, not `click`. Everything is built on the Python standard library, which means it drops cleanly into air-gapped networks, locked-down corporate laptops, and minimal CI images. No dependency resolution, no version conflicts, no supply-chain surface. It also ships a **HAR recorder written entirely on the standard library** — no browser, no devtools session, just a URL and you get a trace.

> 🎯 **In one line**: turn "I have a feeling this is slow" into "request #7 has a 331 ms TTFB, that's 42% of the critical path, add a `preconnect`".

### 🔍 What problem does it solve

| You want to… | Before | With HarScope |
| --- | --- | --- |
| Find what's blocking first paint | Scroll devtools, eyeball the long bars | `harscope slow app.har --by wait` ranks by TTFB instantly |
| Find where the bytes went | Click through every row's Size column | `harscope mime` aggregates transfer size and compression savings |
| Audit third-party scripts | Try to remember who loads whom | `harscope domains` splits requests, bytes, and errors per host |
| Gate a release | "Feels fine to me" | `harscope ci` answers with an exit code |
| Report to leads or clients | Screenshots plus a hand-written doc | `harscope report` emits a self-contained HTML file |
| Capture a trace with no browser | No viable option | `harscope record <url>`, privacy-first |

---

## ✨ Key Features

### 🧊 Genuinely zero dependencies

- 📦 **`dependencies = []`** — not "few dependencies", **none at all**.
- 🔌 Only `dataclasses`, `json`, `csv`, `http.client`, `ssl`, `html.parser`, `urllib.parse`, `zipapp` and friends.
- 🛡️ No supply-chain poisoning surface. Works identically offline or inside a restricted network.
- 🏷️ Ships `py.typed` (PEP 561), so downstream code gets full type hints automatically.

### 🧱 Fault-tolerant parsing: dirty input still yields numbers

Real-world HAR files are never clean. Proxy tools drop fields, `-1` shows up where a size belongs, some exporters omit `startedDateTime` entirely. HarScope's rule is simple: **never throw, always produce a number.**

- 🧯 Size fallback chain: `_transferSize` → `bodySize` → `content.size` → `0`, with every downgrade recorded.
- ⏱️ Missing timestamps are back-filled as "starts right after the previous entry", keeping the timeline monotonic and the span honest.
- 🔤 Numeric fields that arrive as strings, `-1`, or `null` are normalized before they touch any math.
- 🪧 Nothing is silently swallowed — `summary` prints a **data-quality section** telling you exactly which numbers are estimates.

### 📊 Fifteen commands, one question each

| Command | The question it answers |
| --- | --- |
| 🧭 `summary` | Is this session healthy overall? |
| 🌊 `waterfall` | Where did the time actually go? |
| 🌐 `domains` | Which host dominates the request budget? |
| 🧩 `mime` | What kind of resource ate the bytes? |
| 🐢 `slow` | Who is slowest — by total time or by TTFB? |
| 🐘 `largest` | Who is biggest, and what does compression save? |
| 🚦 `status` | Where are the 4xx / 5xx clustered? |
| 📄 `pages` | What were `DOMContentLoaded` and `onLoad` per page? |
| 👯 `dupes` | Did we fire the same request twice? How many bytes wasted? |
| 🛡️ `security` | Plaintext requests? Missing CSP? Cookies without `HttpOnly`? |
| 📤 `export` | Export to JSON / CSV / Markdown / SVG / HTML |
| 📑 `report` | One self-contained HTML report your teammates can double-click |
| 🚧 `ci` | Did this change regress performance? |
| 🎥 `record` | No browser available — how do I produce a HAR? |
| 🩺 `doctor` | Why is the environment misbehaving? |

### 🚧 CI-native: it speaks in exit codes

`harscope ci` uses explicit exit-code semantics and drops straight into GitHub Actions, GitLab CI, or Jenkins:

| Code | Meaning |
| --- | --- |
| `0` | Every gate passed |
| `1` | One or more thresholds were violated |
| `2` | Bad input or unreadable file |

```bash
harscope ci app.har --max-requests 80 --max-transfer-kb 2048 --max-p95-ms 800 --require-https
```

![CI output](docs/images/ci.svg)

### 🎥 A privacy-first HAR recorder

- 🕸️ Overrides `HTTPConnection.connect()` to measure the **real** DNS / TCP / TLS / send / wait / receive phases instead of guessing after the fact.
- 🧵 Pulls up to N first-level static assets over a thread pool, mimicking browser concurrency.
- 🔐 **Never writes response bodies to disk** — only sizes and timings. Auditing a production page doesn't mean stashing real user data.
- 🔁 Follows redirects and records every hop, so you can reconstruct the real redirect chain.

### 🎨 Readable output, in whatever form you need

- 🌈 Detects TTY and honors `NO_COLOR`; `HARSCOPE_FORCE_COLOR=1` forces color back on through a pipe.
- 📐 Column widths account for **East-Asian wide characters**, so mixed CJK/ASCII tables stay aligned.
- 📤 Five export targets: JSON (machine use), CSV (Excel pivots), Markdown (paste into a PR), SVG (embed in docs), HTML (self-contained single file).

---

## 🚀 Quick Start

### 📋 Requirements

| Item | Requirement |
| --- | --- |
| Python | **>= 3.8** (verified on 3.8 through 3.13) |
| OS | Windows / macOS / Linux — no platform-specific code |
| Third-party deps | **None** |
| Disk | ~500 KB |

### ⚡ Up and running in three steps

```bash
# ① Install (no dependencies to resolve — it's instant)
pip install git+https://github.com/gitstq/harscope.git@v1.0.0

# ② Verify
harscope doctor

# ③ Take a look at the bundled sample
harscope summary examples/sample.har
```

<details>
<summary>📺 Expand to see the real <code>summary</code> output</summary>

```
───────────────────────────────── Session Overview ─────────────────────────────────
🔬 HAR Session  Sample Shop · Home
· 14 requests ｜ 5 hosts ｜ HAR 1.2 ｜ Creator HarScope Fixture 1.0

Span            592 ms            Combined       1.12 s
Concurrency     1.89x             Average        80.0 ms
P50             59.6 ms           P95            193 ms
Avg TTFB        42.8 ms           Total size     1.4 MB
Body            1.4 MB            Headers        5.6 KB (0.4%)
Uncompressed    1.9 MB            Saved by gzip 528 KB (27.1%)
HTTPS           92.9%             Cache hits     7.1%

Status codes
  2xx ██████████████████████░░░░░░      11 78.6%
  3xx ██░░░░░░░░░░░░░░░░░░░░░░░░░░       1  7.1%
  4xx ██░░░░░░░░░░░░░░░░░░░░░░░░░░       1  7.1%
  5xx ██░░░░░░░░░░░░░░░░░░░░░░░░░░       1  7.1%

Top hosts
Host                   Requests  Size      Share                Avg       Errors
---------------------- --------  --------- ------------------- --------- ------
files.example.com           1    1.0 MB    █████████████░░░░░   332 ms
cdn.example.com             7    370 KB    █████░░░░░░░░░░░░░  67.3 ms    1
shop.example.com            3    24.3 KB   ░░░░░░░░░░░░░░░░░░  46.0 ms
api.example.com             2    5.2 KB    ░░░░░░░░░░░░░░░░░░  61.6 ms    1
thirdparty.example.com      1    265 B     ░░░░░░░░░░░░░░░░░░  55.7 ms

⚠️  Data quality notes
  - 1/14 entries missing startedDateTime
  - 1/14 entries missing _transferSize; fell back to bodySize estimate
```

</details>

### 🎥 Produce a HAR from scratch

No capture file handy? Record one directly:

```bash
harscope record https://example.com -o trace.har
harscope waterfall trace.har
harscope report trace.har -o report.html
```

### 🧪 Try it without installing

```bash
git clone https://github.com/gitstq/harscope.git
cd harscope
PYTHONPATH=src python -m harscope summary examples/sample.har
```

---

## 📖 Detailed Guide

### 🧭 1. Session overview — `summary`

```bash
harscope summary app.har              # Human-readable report
harscope summary app.har --json       # Structured output for piping
harscope summary app.har --top 20     # Widen the host/MIME leaderboards
```

**How to read it**: `Concurrency` near 1.0 means your requests are effectively serialized — usually a sign you can parallelize with `preconnect` / `preload`. `Saved by gzip` under 50% means your text assets aren't compressed. Headers above 5% of total transfer usually means your cookies got out of hand.

### 🌊 2. Waterfall — `waterfall`

```bash
harscope waterfall app.har            # Slowest 30 entries by default
harscope waterfall app.har --top 60
```

Seven segments, each answering a different question:

| Color | Phase | Meaning |
| --- | --- | --- |
| 🟪 Purple | Blocked | Queued waiting for a connection slot |
| 🟫 Brown | DNS | Name resolution |
| 🟧 Orange | Connect | TCP handshake |
| 🟨 Yellow | TLS | TLS handshake |
| 🟦 Blue | Send | Request upload |
| 🟩 Green | Wait | Time to first byte (TTFB) |
| 🟪 Indigo | Receive | Downloading the body |

> 💡 Green (Wait) dominates → backend problem. Orange/yellow dominate → poor connection reuse, add `preconnect`. Indigo (Receive) dominates → the asset is too big or bandwidth-bound.

### 🌐 3. Host perspective — `domains`

```bash
harscope domains app.har --top 20
```

Instantly surfaces your third-party script offenders. A red flag in the "Secure" column means that host served plaintext HTTP.

### 🧩 4. Resource perspective — `mime`

```bash
harscope mime app.har
```

Shows **transfer size**, **uncompressed size**, and **compression savings** side by side. If a `application/javascript` row shows a 0% saving, compression is off.

### 🐢 5. Slowest requests — `slow`

```bash
harscope slow app.har --top 10               # By total time
harscope slow app.har --top 10 --by wait     # By TTFB — straight at backend latency
```

> 🎯 `--by wait` is the most underrated flag here. A slow *total* usually just means a big asset (easy fix); a slow *TTFB* means the server genuinely has work to do.

### 🐘 6. Largest requests — `largest`

```bash
harscope largest app.har --top 10
```

### 🚦 7. Status codes — `status`

```bash
harscope status app.har
harscope status app.har --json | jq '.errors'
```

### 📄 8. Page perspective — `pages`

```bash
harscope pages app.har
```

For HAR files exported from devtools with `pages` nodes, this reports requests, bytes, span, `DOMContentLoaded`, and `onLoad` per page.

### 👯 9. Duplicate requests — `dupes`

```bash
harscope dupes app.har
```

Detects **same method + same URL** duplicates and totals the bytes you'd save by deduping. Highest return-on-effort optimization in the whole tool.

### 🛡️ 10. Security and compliance — `security`

```bash
harscope security app.har
harscope security app.har --fail-on high      # Exit 1 if any high-severity finding exists
```

Four audit families, scored A through E:

| Family | What it checks |
| --- | --- |
| 🔐 Transport | Plaintext HTTP, mixed content, HTTP → HTTPS redirects |
| 🧱 Response headers | Missing HSTS / CSP / `X-Content-Type-Options` / `Referrer-Policy` / `X-Frame-Options` / `Permissions-Policy` |
| 🍪 Cookie flags | Whether `Secure` / `HttpOnly` / `SameSite` are set |
| 🕵️ Disclosure | `token` / `password` / `secret` / `api_key` in URLs or headers; server version strings in responses |

**Scoring model** (100 points total): transport security 30 + header compliance 30 + findings 40. The sample file deliberately contains high-severity findings (mixed content, credentials in URL), so it lands at an E — useful for demonstrating what a failing gate looks like.

### 📤 11. Exporting — `export`

```bash
harscope export app.har --format json     -o report.json   --entries
harscope export app.har --format csv      -o entries.csv             # UTF-8 BOM, opens cleanly in Excel
harscope export app.har --format markdown -o report.md
harscope export app.har --format svg      -o waterfall.svg
harscope export app.har --format html     -o report.html
harscope export app.har --format html     -o report.html --no-security --force
```

| Format | Best used for |
| --- | --- |
| `json` | Further processing, storing results, feeding a dashboard |
| `csv` | Excel pivot tables, handing raw rows to a colleague |
| `markdown` | Pasting straight into a PR, issue, or weekly report |
| `svg` | Embedding into Confluence / Notion / internal wiki |
| `html` | A self-contained single file (inlined CSS and SVG) — email it or double-click it |

### 🚧 12. CI quality gate — `ci`

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

Every flag is optional — set only what you actually care about, everything else is skipped. Each violation comes with a **concrete remediation hint**, not just a red X.

<details>
<summary>🔧 Copy-paste GitHub Actions workflow</summary>

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

      # Zero dependencies: install is instant, no cache needed
      - run: pip install git+https://github.com/gitstq/harscope.git@v1.0.0

      # Record the page under test (works headless)
      - run: harscope record https://staging.example.com -o trace.har --assets 20

      # Gate: fails the job with a non-zero exit if any threshold is breached
      - run: harscope ci trace.har --max-requests 80 --max-transfer-kb 2048 --max-p95-ms 800 --require-https

      # Always publish the report, pass or fail
      - if: always()
        run: harscope report trace.har -o harscope-report.html --force
      - if: always()
        uses: actions/upload-artifact@v4
        with:
          name: harscope-report
          path: harscope-report.html
```

</details>

### 🎥 13. Recording a HAR — `record`

```bash
harscope record https://example.com -o trace.har
harscope record https://example.com -o trace.har --assets 20 --timeout 15
harscope record https://example.com -o trace.har --cross-host          # Also fetch cross-origin assets
harscope record https://example.com -o trace.har --header "Cookie: k=v"
harscope record https://internal.test -o trace.har --insecure          # Self-signed certs
```

> 🔐 **Privacy note**: recording stores **URLs, request headers, response headers, sizes, and timings only — never response bodies**. Safe to point at production pages.

### 🩺 14. Environment self-check — `doctor`

```bash
harscope doctor
harscope doctor --json
```

Prints your Python version, platform, OpenSSL version, and terminal color state — the fastest way to answer "why are the colors gone?" or "why did TLS fail?"

### 🐍 15. Using it as a Python library

HarScope isn't only a CLI. It's a library you can drop into your own platform.

```python
from harscope import load, loads, analyze

# From a file
har = load("app.har")

# Or straight from a string / bytes
har = loads(open("app.har", encoding="utf-8").read())

analysis = analyze(har)

print(f"Requests:      {analysis.total_requests}")
print(f"Hosts:         {analysis.unique_hosts}")
print(f"Session span:  {analysis.duration_ms:.1f} ms")
print(f"P95:           {analysis.p95_ms:.1f} ms")
print(f"Transfer size: {analysis.transfer_bytes} bytes")
print(f"Gzip savings:  {analysis.compression_saving_ratio:.1%}")
print(f"HTTPS share:   {analysis.https_ratio:.1%}")
print(f"Concurrency:   {analysis.parallelism:.2f}x")

# Every headline metric in one dict, ready for json.dumps()
summary = analysis.summary_dict()
```

**Full metric surface:**

| Attribute / method | Returns | Description |
| --- | --- | --- |
| `analysis.total_requests` | `int` | Total entries |
| `analysis.unique_hosts` / `hosts` | `int` / `Set[str]` | Distinct hosts |
| `analysis.duration_ms` | `float` | Session span, first start to last end |
| `analysis.total_time_ms` | `float` | Sum of all entry times |
| `analysis.parallelism` | `float` | Combined time divided by span |
| `analysis.average_ms` / `p50_ms` / `p95_ms` / `p99_ms` | `float` | Percentiles via linear interpolation |
| `analysis.average_wait_ms` / `p95_wait_ms` | `float` | TTFB statistics |
| `analysis.transfer_bytes` / `body_transfer_bytes` / `header_bytes` | `int` | Byte breakdown |
| `analysis.uncompressed_body_bytes` | `int` | Bodies after decompression |
| `analysis.compression_saving_bytes` / `_ratio` | `int` / `float` | Compression gains |
| `analysis.https_ratio` / `cache_hit_ratio` / `success_ratio` | `float` | Ratio metrics |
| `analysis.insecure_requests` | `int` | Plaintext HTTP count |
| `analysis.status_classes` / `status_codes` | `Dict` | Status aggregation |
| `analysis.error_entries` / `client_error_entries` | `List[HarEntry]` | Failing requests |
| `analysis.domain_stats(n)` | `List[DomainStat]` | Per-host rollup |
| `analysis.mime_stats(n)` | `List[MimeStat]` | Per-MIME-type rollup |
| `analysis.duplicates(top=n)` | `List[DuplicateGroup]` | Duplicate groups |
| `analysis.redirect_chains()` | `List[List[HarEntry]]` | Reconstructed redirect chains |
| `analysis.waterfall(limit=n)` | `List[WaterfallRow]` | Waterfall rows |
| `analysis.page_stats()` | `List[PageStat]` | Per-page rollup |
| `analysis.slowest(n, by="time"\|"wait")` | `List[HarEntry]` | Slowest leaderboard |
| `analysis.largest(n)` | `List[HarEntry]` | Largest leaderboard |
| `analysis.summary_dict()` | `Dict[str, Any]` | Everything, as a dict |

**Call the exporters and the audit directly:**

```python
from harscope import load, analyze
from harscope.exporters import to_json, to_markdown, to_csv, to_svg_waterfall, to_html_report
from harscope.security import audit

har = load("app.har")
analysis = analyze(har)
sec = audit(har)

print(f"Security score: {sec.score}/100 (grade {sec.grade})")
for f in sec.findings:
    print(f"[{f.severity}] {f.category}: {f.message}")

# Build artifacts
html = to_html_report(analysis, audit=sec, waterfall_limit=40)
open("report.html", "w", encoding="utf-8").write(html)

open("report.md", "w", encoding="utf-8").write(to_markdown(analysis, audit=sec))
open("entries.csv", "w", encoding="utf-8").write(to_csv(analysis.entries))
open("waterfall.svg", "w", encoding="utf-8").write(to_svg_waterfall(analysis, limit=40))
```

**Reuse the recorder from your own code:**

```python
from harscope.recorder import record, RecordOptions

options = RecordOptions(
    timeout=15.0,
    max_assets=20,
    max_redirects=5,
    same_host_only=True,
    headers={"Cookie": "session=abc"},
)
har_dict = record("https://example.com", options)   # returns a standard HAR dict

import json
json.dump(har_dict, open("trace.har", "w"), ensure_ascii=False, indent=2)
```

**Error handling:**

```python
from harscope import load, analyze
from harscope.exceptions import (
    HarScopeError, HarParserError, NetworkRecordError, ExportError,
)

try:
    analysis = analyze(load("app.har"))
except HarParserError as exc:
    print(f"Failed to parse HAR: {exc}")
    for warning in exc.warnings:
        print(f"  warning: {warning}")
except HarScopeError as exc:
    print(f"HarScope error: {exc}")
```

> 🧯 `HarParserError` collects **non-fatal problems** into `exc.warnings` rather than crashing — which matters a lot when you're batch-processing hundreds of capture files.

### 🔤 Global flags

| Flag | Effect |
| --- | --- |
| `--json` | Emit structured JSON — pair it with `jq` |
| `--no-color` | Disable ANSI colors (same as `NO_COLOR=1`) |
| `--version` | Print the version |
| `-h` / `--help` | Show help |

**Environment variables:**

| Variable | Effect |
| --- | --- |
| `NO_COLOR=1` | Turn off terminal colors |
| `HARSCOPE_FORCE_COLOR=1` | Force colors even when piping |

---

## 💡 Design & Iteration

### 🧠 Why insist on zero dependencies

This is the project's core — and most counterintuitive — decision.

**What it costs**: giving up `requests` (so TLS plumbing is hand-rolled), `pydantic` (validation written by hand), `rich` (terminal layout computed manually), `click` (argparse written the long way). Roughly 30% more code.

**What it buys**:

1. **It runs anywhere** — an offline laptop, an air-gapped corporate network, a size-constrained CI image, `python:alpine`. Install and go.
2. **Zero supply-chain attack surface.** No transitive dependencies means no transitive risk. For a tool that **lives inside CI and reads real capture data**, that matters far more than the lines of code saved.
3. **Install time near zero.** `pip install` never has to resolve a dependency tree; in a pipeline it's one clean step.
4. **No dependency conflicts ever.** No worrying that a downstream project's `pydantic<2` pin fights with HarScope.

The test is simple: **this thing runs inside other people's CI.** A CI tool's dependencies become everyone's technical debt.

### 🧱 Why "tolerate first, compute second"

HAR is an **exchange format written by tools for tools**, and dozens of tools write it with wildly varying quality. Strict parsing is the wrong answer here:

- Rejecting `_transferSize: -1` → users conclude "it doesn't work", not "how rigorous".
- Dropping any entry missing `startedDateTime` → the statistics quietly drift while nobody notices.

HarScope's compromise: **produce a value wherever possible, but record every downgrade in `notes` and surface it at the bottom of `summary`.** A metric may be an estimate, but the user must always know it's an estimate. That's the floor for anything calling itself forensics.

### ⏱️ A real lesson from timeline back-filling

The first back-fill implementation summed *all* preceding entry times onto the missing entry. Session span ballooned from a true 447 ms to 1,467 ms, and concurrency inflated from 1.49× to 2.57× — numbers that looked plausible enough to believe and were completely wrong. Switching to "start right after the previous entry" brought every metric back into a sane range immediately.

The lesson: **a performance tool's bugs don't crash, they hand you a wrong number you end up trusting.** That's why every time- and byte-related metric in this project carries unit tests that assert on order of magnitude, not just on "runs without error".

### 📐 Why security scoring isn't simple deduction

The original model deducted points per finding, which pushed the sample file straight to 0 / grade E — it contained mixed content and credentials in a URL. That might read as "your site is terrible", but it conveys nothing actionable: which thing gets fixed first?

Component weighting reads much better: **transport 30 + headers 30 + findings 40.** Even a site with high-severity findings can earn a C if its transport layer and headers are solid. **The score expresses overall security posture; the `findings` list carries the actionable items.** Scores are for managers, findings are for engineers.

### 🗺️ Roadmap

| Version | Planned | Status |
| --- | --- | --- |
| **v1.0.0** | 15 commands, 5 export targets, built-in recorder, 126 unit tests, trilingual docs | ✅ Released |
| v1.1.0 | HAR diffing (`harscope diff A.har B.har`) and regression trend tracking | 📋 Planned |
| v1.2.0 | Approximate Core Web Vitals (LCP / FID / CLS inferred from HAR) | 📋 Planned |
| v1.3.0 | JSON-Schema-level HAR validation report, `--strict` mode | 💡 Exploring |
| v2.0.0 | Prometheus exporter, Grafana dashboard templates, webhook alerting | 💡 Exploring |

**Explicit non-goals**: adding third-party dependencies, embedding browser automation, uploading HAR files to a cloud service for parsing, or HTTP/3-specific metrics (they must be exposed server-side and can't be derived reliably from HAR).

---

## 📦 Packaging & Deployment

HarScope is a **tool / library**, so it ships no platform-specific installers. Instead you get four ways to acquire it.

### 🐍 Option 1 — pip install (recommended)

```bash
# Pin a release
pip install git+https://github.com/gitstq/harscope.git@v1.0.0

# Upgrade to latest main
pip install --upgrade git+https://github.com/gitstq/harscope.git

# From a checkout
git clone https://github.com/gitstq/harscope.git && cd harscope
pip install --no-deps .

# Editable install for development
pip install --no-deps -e .
```

This gives you a global `harscope` command; `python -m harscope` is equivalent.

### 📀 Option 2 — build the distribution

```bash
make wheel                     # dist/harscope-1.0.0-py3-none-any.whl
python -m build                # wheel + sdist
pip install dist/*.whl         # verify it installs
```

The wheel is `py3-none-any` — one artifact for every platform and Python version.

### 🧳 Option 3 — zipapp single file (portable, nothing installed)

```bash
make zipapp                    # dist/harscope.pyz
python dist/harscope.pyz summary app.har          # run it
python3.11 dist/harscope.pyz waterfall app.har    # or pin an interpreter
```

A `.pyz` is an executable zip containing the whole package — **handing it to a colleague means sending one file**, and any Python will run it.

### 🏃 Option 4 — run with nothing installed

```bash
git clone https://github.com/gitstq/harscope.git && cd harscope
PYTHONPATH=src python3 -m harscope summary examples/sample.har
# or use the helper script
bash scripts/run.sh summary examples/sample.har
```

### 🧪 Local development

```bash
make install         # Install into the current environment
make dev             # Editable install
make test            # Run all 126 unit tests
make test-net        # Include the network recorder tests
make smoke           # CLI smoke test
make clean           # Remove build artifacts
```

### 🔁 Deploying inside CI

Zero dependencies makes CI integration trivial — no dependency cache, no virtualenv warmup:

```yaml
- run: pip install git+https://github.com/gitstq/harscope.git@v1.0.0
- run: harscope ci trace.har --max-requests 80 --require-https
```

See the full workflow under "🚧 CI quality gate" above.

### 📁 Project layout

```
harscope/
├── src/harscope/
│   ├── __init__.py       # Package entrypoint, exports load / loads / analyze
│   ├── __main__.py       # python -m harscope entrypoint
│   ├── model.py          # HAR 1.2 data model (fault-tolerant, nullable)
│   ├── parser.py         # Parsing and timeline back-filling
│   ├── analyze.py        # Metric aggregation (P50/P95/P99, hosts, MIME, waterfall)
│   ├── security.py       # Security and compliance audit
│   ├── exporters.py      # JSON / CSV / Markdown / SVG / HTML exports
│   ├── recorder.py       # Standard-library-only HAR recorder
│   ├── render.py         # Terminal rendering (colors, tables, waterfall)
│   ├── cli.py            # CLI with 15 subcommands
│   ├── exceptions.py     # Exception hierarchy
│   └── py.typed          # PEP 561 type marker
├── tests/                # 126 unit tests using only stdlib unittest
├── examples/sample.har   # Sample capture file
├── scripts/              # One-shot run / build / test scripts
├── .github/workflows/    # CI across 3 OSes × 6 Python versions
├── pyproject.toml        # PEP 517/518 packaging metadata
├── Makefile
├── CONTRIBUTING.md
├── CHANGELOG.md
└── LICENSE
```

---

## 🤝 Contributing

Stars ⭐, issues 🐛, and pull requests 🔧 are all welcome. The full rules live in [CONTRIBUTING.md](./CONTRIBUTING.md); the essentials:

### 🔧 Get set up

```bash
git clone https://github.com/gitstq/harscope.git
cd harscope
pip install --no-deps -e .
make test                    # Must be fully green
```

### 🧾 Angular commit convention

Commit messages must follow `<type>(<scope>): <subject>`. This is a merge requirement:

```
feat(analyze): add P99 latency percentile
fix(parser): fix timeline back-fill overflow when startedDateTime is missing
docs(readme): add Traditional Chinese usage examples
refactor(security): switch scoring to a weighted three-part model
test(cli): cover every ci threshold branch
```

Allowed types: `feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci` `chore` `revert`.

### 🚫 Project red lines

- ❌ **No third-party runtime dependencies.** This is the project's reason to exist.
- ❌ Don't lower the Python floor (currently `>=3.8`).
- ❌ Don't delete or weaken existing test assertions.
- ❌ Don't write response bodies into any output or export.
- ❌ Any behavior change must update **all three READMEs** (Simplified / Traditional / English).

### 🐛 Filing issues

Never paste raw HAR content containing cookies, `Authorization` headers, or real user data. Export the aggregates with `harscope export --format json` first, or hand-scrub a minimal reproduction.

---

## 📄 License

Released under the **[MIT License](./LICENSE)**. You may:

- ✅ Use, copy, modify, merge, publish, distribute, sublicense, and sell copies — **commercially or otherwise**;
- ✅ Embed it in closed-source commercial products;
- ✅ Do all of the above for free.

**The only requirement**: keep the copyright and permission notice in all copies or substantial portions.

**Disclaimer**: the software is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors or copyright holders be liable for any claim, damages, or other liability.

Read the full legal text in [LICENSE](./LICENSE).

---

<div align="center">

**If HarScope helped you catch the request that was quietly wrecking your first paint, drop a ⭐ — it's the only fuel a zero-dependency project runs on.**

[⬆ Back to top](#-harscope) ｜ [Open an issue](https://github.com/gitstq/harscope/issues) ｜ [Contributing guide](./CONTRIBUTING.md)

🌏 [简体中文](./README.md) ｜ [繁體中文](./README.zh-TW.md) ｜ **English**

</div>
