.PHONY: install ready format lint type-check test test-cov run compile eval eval-smoke eval-clean cursor claude v verbose

install:
	uv sync --all-extras
	uv run -- prek install
	cp .env.example .env

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
# Note: `make … -v` is Make's --version; use the `v` / `verbose` goal instead.
RUNTIME := $(firstword $(filter cursor claude,$(MAKECMDGOALS)))
ifeq ($(RUNTIME),)
RUNTIME := cursor
endif
VERBOSE := $(if $(filter v verbose,$(MAKECMDGOALS)),--verbose,)

eval:
	uv run -- python eval/bench.py --provider $(RUNTIME) $(VERBOSE)

eval-smoke:
	uv run -- python eval/bench.py --smoke --provider $(RUNTIME) $(VERBOSE)

cursor claude v verbose:
	@:

eval-clean:
	rm -rf eval/results

compile:
	uv run --no-dev -- nuitka src/app.py \
		--standalone \
		--onefile \
		--lto=yes \
		--assume-yes-for-downloads \
		--output-filename=codeparse \
		--python-flag=no_warnings \
		--include-package=src \
		--include-distribution-metadata=caio \
		--include-distribution-metadata=aiofile \
		--nofollow-import-to=src.tests \
		--nofollow-import-to=pytest \
		--include-data-files=pyproject.toml=pyproject.toml \
		--include-data-files=src/schema.sql=src/schema.sql \
		--noinclude-data-files=src/tests/* \
		--output-dir=dist/
