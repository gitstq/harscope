#!/usr/bin/env bash
#
# HarScope · 一键测试
#
# 默认只跑离线用例（0.3 秒）；
# 需要联网验证录制器时： HARSCOPE_TEST_NETWORK=1 ./scripts/test.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
command -v "${PYTHON_BIN}" > /dev/null 2>&1 || PYTHON_BIN="python"

cd "${ROOT}"

echo "==> Python $("${PYTHON_BIN}" -c 'import platform; print(platform.python_version())')"
echo "==> 离线单元测试"
"${PYTHON_BIN}" -m unittest discover -s tests -v

if [ "${HARSCOPE_TEST_NETWORK:-0}" = "1" ]; then
  echo "==> 含网络的录制器用例"
  HARSCOPE_TEST_NETWORK=1 "${PYTHON_BIN}" -m unittest discover -s tests
fi

echo "==> CLI 冒烟"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
PYTHONPATH="${ROOT}/src" "${PYTHON_BIN}" -c "
import sys; sys.path.insert(0, 'tests')
from har_fixture import sample_json
open(r'${TMP_DIR}/sample.har', 'w', encoding='utf-8').write(sample_json())
"
for cmd in summary domains mime slow status pages dupes waterfall; do
  PYTHONPATH="${ROOT}/src" "${PYTHON_BIN}" -m harscope --no-color "${cmd}" "${TMP_DIR}/sample.har" > /dev/null \
    && echo "    ✅ ${cmd}" || echo "    ❌ ${cmd}"
done
PYTHONPATH="${ROOT}/src" "${PYTHON_BIN}" -m harscope --no-color report "${TMP_DIR}/sample.har" \
    -o "${TMP_DIR}/report.html" > /dev/null && echo "    ✅ report"
PYTHONPATH="${ROOT}/src" "${PYTHON_BIN}" -m harscope --no-color export "${TMP_DIR}/sample.har" \
    --format md -o "${TMP_DIR}/report.md" > /dev/null && echo "    ✅ export(md)"
PYTHONPATH="${ROOT}/src" "${PYTHON_BIN}" -m harscope --no-color security "${TMP_DIR}/sample.har" > /dev/null \
    && echo "    ✅ security"
PYTHONPATH="${ROOT}/src" "${PYTHON_BIN}" -m harscope --no-color doctor > /dev/null && echo "    ✅ doctor"
echo "==> 全部通过"
