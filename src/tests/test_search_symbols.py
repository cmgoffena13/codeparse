"""Tests for search_symbols MCP query."""

import shutil
from pathlib import Path

from src.codeparse_mcp.search_symbols import search_symbols
from src.db import CodeDB
from src.processor import CodeProcessor


def _index(tmp_path: Path, python_fixtures_dir: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(python_fixtures_dir / "search_symbols", root)
    db = CodeDB(root)
    CodeProcessor(db, root).process()
    db.close()
    return root


def test_search_symbols_excludes_is_test_by_default(
    tmp_path: Path, python_fixtures_dir: Path
) -> None:
    root = _index(tmp_path, python_fixtures_dir)
    db = CodeDB(root)
    try:
        out = search_symbols(db, "format_model", limit=20)
        assert "pkg.prod.format_model" in out
        assert "test_format_model" not in out
        assert "tests/" not in out
        assert "Legend: # = Rank" in out
        assert "pkg/prod.py" in out
        assert any(
            line.startswith("  #") and " • " in line and "pkg.prod.format_model" in line
            for line in out.splitlines()
        )
        assert "Sig:" not in out
        assert "Doc:" not in out
    finally:
        db.close()


def test_search_symbols_include_tests(tmp_path: Path, python_fixtures_dir: Path) -> None:
    root = _index(tmp_path, python_fixtures_dir)
    db = CodeDB(root)
    try:
        out = search_symbols(db, "format_model", limit=20, include_tests=True)
        assert "pkg.prod.format_model" in out
        assert "test_format_model" in out
    finally:
        db.close()


def test_search_symbols_groups_by_file_with_rank(tmp_path: Path, python_fixtures_dir: Path) -> None:
    root = _index(tmp_path, python_fixtures_dir)
    db = CodeDB(root)
    try:
        out = search_symbols(db, "format_model", limit=20)
        hits = [line for line in out.splitlines() if line.startswith("  #")]
        assert hits
        ranks: list[int] = []
        for line in hits:
            # "  #3 • qualified_name" with the rank padded to the widest rank
            parts = line.split()
            assert parts[0].startswith("#")
            assert parts[1] == "•"
            ranks.append(int(parts[0].removeprefix("#")))
        assert sorted(ranks) == list(range(1, len(ranks) + 1))
        name_at = [line.index(line.split()[-1]) for line in hits]
        assert len(set(name_at)) == 1
    finally:
        db.close()
