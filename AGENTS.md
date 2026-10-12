# Agents Guide

## Styling
 - DO NOT write comments. The user will add comments if necessary.

## Python Standards
 - Always use absolute import paths, not relative or partial imports.
 - Always import packages at the top of the file.
 - Always write a test before implementing a code change.
 - Always use ONE return statement when writing functions.
 - NEVER use `dataclass`. Use the `pydantic` package instead.
 - NEVER add `from __future__ import annotations` to a file.
 - DO NOT use `global` ever.

## Testing Standards
 - Scan before test creation to determine if a new test needs written or a test can be modified.
 - Write tests in `pytest` format (functions, not classes). Ex. `def test_retry`
 - Always put test fixtures in `conftest.py`
 - Always put test/synthetic data within its own file in the `fixtures` directory for reuse among tests.

## Validation
 - `make ready` must pass after every change.