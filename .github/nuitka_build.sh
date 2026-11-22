#!/usr/bin/env bash
set -euo pipefail

JOBS="${NUITKA_JOBS:-}"
if [[ -z "${JOBS}" ]]; then
  JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)"
fi
if [[ -z "${JOBS}" ]]; then
  JOBS="$(sysctl -n hw.ncpu 2>/dev/null || true)"
fi
if [[ -z "${JOBS}" || ! "${JOBS}" =~ ^[0-9]+$ ]]; then
  JOBS=4
fi

OUTPUT_NAME="codeparse"
if [[ "${OS:-}" == "Windows_NT" || "${RUNNER_OS:-}" == "Windows" ]]; then
  OUTPUT_NAME="codeparse.exe"
fi

uv run --no-dev -- nuitka \
  --onefile \
  --lto=no \
  --jobs="${JOBS}" \
  --assume-yes-for-downloads \
  src/app.py \
  --output-filename="${OUTPUT_NAME}" \
  --python-flag="no_warnings" \
  --include-package=src \
  --include-package=certifi \
  --include-package-data=certifi \
  --include-distribution-metadata=caio \
  --include-distribution-metadata=aiofile \
  --nofollow-import-to=pytest \
  --nofollow-import-to=fastmcp.cli \
  --nofollow-import-to=certifi.tests \
  --noinclude-unittest-mode=nofollow \
  --noinclude-IPython-mode=nofollow \
  --include-data-files=pyproject.toml=pyproject.toml \
  --include-data-files=src/schema.sql=src/schema.sql \
  --include-data-files=src/drop_schema.sql=src/drop_schema.sql \
  --output-dir=dist/
