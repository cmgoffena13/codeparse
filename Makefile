.PHONY: install ready format lint type-check test test-cov run compile eval eval-smoke eval-clean cursor claude v verbose

install:
	uv sync --all-extras
	uv run -- prek install
	cp .env.example .env

clean:
	rm -rf dist/
	rm -rf __pycache__/
	rm -rf .ruff_cache/
	rm -rf .pytest_cache/
	rm -f .coverage
	rm -rf .codeparse/
	rm -rf eval/cache/
	rm -rf eval/results/

reset: clean
	uv venv --clear
	$(MAKE) install

upgrade:
	uv sync --upgrade --all-extras

run:
	uv run -- python main.py

ready: lint format type-check test-cov

format:
	uv run -- ruff format

lint:
	uv run -- ruff check --fix

type-check:
	uv run -- ty check

test:
	uv run -- pytest -v -n auto

test-cov:
	uv run -- pytest --cov=src --cov-report=term-missing

# Usage:
#   make eval-smoke
#   make eval-smoke claude
#   make eval-smoke v
#   make eval-smoke verbose
#   make eval cursor
#   make eval-smoke v TASK=search-dialect-transpilation ARM=codeparse
# Note: `make … -v` is Make's --version; use the `v` / `verbose` goal instead.
TASK_ARGS := $(if $(TASK),--tasks $(TASK),)
ARM_ARGS := $(if $(ARM),--arm $(ARM),)
RUNTIME := $(firstword $(filter cursor claude,$(MAKECMDGOALS)))
ifeq ($(RUNTIME),)
RUNTIME := cursor
endif
VERBOSE := $(if $(filter v verbose,$(MAKECMDGOALS)),--verbose,)

eval:
	uv run -- python eval/bench.py --provider $(RUNTIME) $(VERBOSE) $(TASK_ARGS) $(ARM_ARGS)

eval-smoke:
	uv run -- python eval/bench.py --smoke --provider $(RUNTIME) $(VERBOSE) $(TASK_ARGS) $(ARM_ARGS)

cursor claude v verbose:
	@:

eval-clean:
	rm -rf eval/results

compile:
	rm -rf dist
	uv run --no-dev -- nuitka src/app.py \
		--standalone \
		--onefile \
		--lto=yes \
		--assume-yes-for-downloads \
		--output-filename=codeparse \
		--python-flag=no_warnings \
		--include-package=src \
		--include-package=certifi \
		--include-package-data=certifi \
		--include-distribution-metadata=caio \
		--include-distribution-metadata=aiofile \
		--nofollow-import-to=src.tests \
		--nofollow-import-to=pytest \
		--nofollow-import-to=fastmcp.cli \
		--include-data-files=pyproject.toml=pyproject.toml \
		--include-data-files=src/schema.sql=src/schema.sql \
		--include-data-files=src/drop_schema.sql=src/drop_schema.sql \
		--noinclude-data-files=src/tests/* \
		--output-dir=dist/
