#!/usr/bin/env bash
#
# HarScope · 本地一键运行入口
#
# 不需要 pip install，也不需要联网安装依赖。
# 用法：
#   ./scripts/run.sh summary path/to/trace.har
#   ./scripts/run.sh report path/to/trace.har -o out.html
#   ./scripts/run.sh --help
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"

PYTHON_BIN="${PYTHON:-python3}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

# 自动关闭管道场景下的颜色，输出更友好
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

if [ "$#" -eq 0 ]; then
  set -- "--help"
fi

exec "${PYTHON_BIN}" -m harscope "$@"
