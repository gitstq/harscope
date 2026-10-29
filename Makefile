.PHONY: help install dev test build wheel sdist zipapp clean dist-check format lint run

PYTHON ?= python3
SRC     := src
DIST    := dist

help: ## 显示可用目标
	@echo "HarScope · 可用目标"
	@echo "  make install      安装到当前 Python 环境（--no-deps）"
	@echo "  make dev          以可编辑模式安装"
	@echo "  make test         运行单元测试"
	@echo "  make test-net     运行含网络录制器的测试"
	@echo "  make run CMD=...  免安装运行，如 make run CMD='summary examples/sample.har'"
	@echo "  make build        构建 wheel + sdist + zipapp"
	@echo "  make wheel        只构建 wheel"
	@echo "  make zipapp       只构建 zipapp 单文件产物"
	@echo "  make clean        清理构建产物"

install: ## 安装到当前环境
	$(PYTHON) -m pip install --no-deps .

dev: ## 可编辑模式安装
	$(PYTHON) -m pip install --no-deps -e .

test: ## 运行单元测试
	$(PYTHON) -m unittest discover -s tests -v

test-net: ## 运行含网络的测试
	HARSCOPE_TEST_NETWORK=1 $(PYTHON) -m unittest discover -s tests -v

smoke: ## CLI 冒烟测试
	./scripts/test.sh

run: ## 免安装运行：make run CMD="summary examples/sample.har"
	PYTHONPATH=$(SRC) $(PYTHON) -m harscope $(CMD)

build: test wheel zipapp ## 构建全部产物

wheel: ## 构建 wheel 与 sdist
	$(PYTHON) -m pip wheel --no-deps --no-build-isolation --wheel-dir $(DIST) .

sdist: ## 构建源码分发包
	$(PYTHON) -m pip download --no-deps --no-build-isolation --no-binary :all: --dest $(DIST) .

zipapp: ## 构建 zipapp 单文件产物
	@mkdir -p $(DIST) build/zipapp
	rm -rf build/zipapp/harscope
	cp -r $(SRC)/harscope build/zipapp/harscope
	$(PYTHON) -c "import compileall; compileall.compile_dir('build/zipapp/harscope', quiet=1, optimize=2)"
	$(PYTHON) -c "import zipapp; zipapp.create_archive('build/zipapp', '$(DIST)/harscope.pyz', interpreter='/usr/bin/env python3', main='harscope.__main__:main')"
	@echo "已生成 $(DIST)/harscope.pyz"

clean: ## 清理构建产物
	rm -rf build $(DIST) .pytest_cache src/*.egg-info
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	find . -name "*.pyc" -delete
