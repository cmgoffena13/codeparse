.PHONY: install ready format lint type-check test test-cov run compile eval eval-smoke eval-clean cursor claude v verbose bump major minor patch

install:
	uv sync --all-extras
	uv run -- prek install
	cp .env.example .env

clean:
	rm -rf dist/ __pycache__/ .ruff_cache/ .pytest_cache/ .codeparse/ eval/cache/.codeparse/ eval/results/
	rm -f .coverage

reset: clean
	uv venv --clear
	$(MAKE) install

upgrade:
	uv sync --upgrade --all-extras

run:
	rm -rf .codeparse/
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
	chmod +x .github/nuitka_build.sh
	./.github/nuitka_build.sh

bump:
	uv version --bump $(filter major minor patch,$(MAKECMDGOALS))

major minor patch:
	@: