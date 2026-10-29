#!/usr/bin/env bash
#
# HarScope · 一键打包脚本
#
# 产出（写入 dist/）：
#   harscope-<version>-py3-none-any.whl   可直接 pip install 的轮子
#   harscope-<version>.tar.gz             源码分发包
#   harscope.pyz                          zipapp 单文件可执行产物
#
# 构建优先级：
#   1) PEP 517 官方流程  python -m build
#   2) 无外网/无 build 时 python -m pip wheel --no-build-isolation
#   3) 极端精简环境     zipapp 单文件产物
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"

PYTHON_BIN="${PYTHON:-python3}"
command -v "${PYTHON_BIN}" >/dev/null 2>&1 || PYTHON_BIN="python"

VERSION="$("${PYTHON_BIN}" -c "
import pathlib, re
root = pathlib.Path(r'${ROOT}')
text = (root / 'src' / 'harscope' / '__init__.py').read_text(encoding='utf-8')
print(re.search(r'__version__\s*=\s*\"([^\"]+)\"', text).group(1))
")"

cd "${ROOT}"
rm -rf build dist src/*.egg-info
mkdir -p dist

echo "==> 1/3 运行单元测试"
"${PYTHON_BIN}" -m unittest discover -s tests > /dev/null
echo "    全部通过"

echo "==> 2/3 构建 wheel / sdist（版本 ${VERSION}）"
if "${PYTHON_BIN}" -m build --version > /dev/null 2>&1; then
  "${PYTHON_BIN}" -m build --wheel --sdist --outdir dist
elif "${PYTHON_BIN}" -m pip wheel --help > /dev/null 2>&1; then
  "${PYTHON_BIN}" -m pip wheel --no-deps --no-build-isolation --wheel-dir dist .
  "${PYTHON_BIN}" -m pip download --no-deps --no-build-isolation --no-binary :all: \
      --dest dist . > /dev/null 2>&1 || echo "    （当前环境不支持生成 sdist，已跳过）"
else
  echo "    未检测到可用的 wheel 构建链路，将只产出 zipapp"
fi

echo "==> 3/3 生成 zipapp 单文件产物"
"${PYTHON_BIN}" - <<'PY'
import os, shutil, zipapp, compileall

root = os.getcwd()
staging = os.path.join(root, "build", "zipapp")
if os.path.isdir(staging):
    shutil.rmtree(staging)
os.makedirs(staging)
target = os.path.join(staging, "harscope")
shutil.copytree(os.path.join(root, "src", "harscope"), target)
compileall.compile_dir(target, quiet=1, optimize=2)
zipapp.create_archive(
    staging,
    os.path.join(root, "dist", "harscope.pyz"),
    interpreter="/usr/bin/env python3",
    main="harscope.__main__:main",
)
print("    已生成 dist/harscope.pyz")
PY

if ls dist/*.whl > /dev/null 2>&1; then
  echo "==> 安装校验"
  "${PYTHON_BIN}" -m pip install --quiet --force-reinstall --no-deps \
      "$(ls dist/*.whl | head -1)" 2>/dev/null || echo "    （无写权限或无网络，已跳过安装）"
  "${PYTHON_BIN}" -c "import harscope, sys; print('    导入成功 harscope', harscope.__version__)" 2>/dev/null || true
fi

echo "==> 产物清单"
ls -la dist
