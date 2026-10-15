"""Tests for get_directory_tree MCP query."""

from pathlib import Path

from src.codeparse_mcp.directory_tree import get_directory_tree
from src.db import CodeDB
from src.processor import CodeProcessor


def _index(root: Path) -> None:
    (root / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    pkg = root / "pkg"
    core = pkg / "core"
    core.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (core / "__init__.py").write_text("", encoding="utf-8")
    (core / "dialect.py").write_text(
        "def format_model() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (core / "other.py").write_text("x = 1\n", encoding="utf-8")
    (core / "notes.py").write_text("# just a comment\n", encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_dialect.py").write_text(
        "def test_format_model() -> None:\n    pass\n",
        encoding="utf-8",
    )
    db = CodeDB(root)
    CodeProcessor(db, root).process()
    db.close()


def test_directory_tree_full(tmp_path: Path) -> None:
    _index(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_directory_tree(db)
        assert "Legend:" not in out
        assert ".\n" in out
        assert "dialect.py" in out
        assert "test_dialect.py" in out
    finally:
        db.close()


def test_directory_tree_path_scopes(tmp_path: Path) -> None:
    _index(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_directory_tree(db, path="pkg/core")
        assert "Legend:" not in out
        assert "pkg/core/" in out
        assert "dialect.py" in out
        assert "other.py" in out
        assert "notes.py (2L, 0S)" in out
        assert "pkg/__init__.py" not in out
        assert "test_dialect.py" not in out

        pkg = get_directory_tree(db, path="pkg")
        assert "pkg/" in pkg
        assert "core/" in pkg
        assert "dialect.py" in pkg
        assert "__init__.py" in pkg
        assert "test_dialect.py" not in pkg

        with_slash = get_directory_tree(db, path="pkg/core/")
        assert "dialect.py" in with_slash
    finally:
        db.close()


def test_directory_tree_path_file_rejected(tmp_path: Path) -> None:
    _index(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_directory_tree(db, path="pkg/core/dialect.py")
        assert "No directory matches" in out
    finally:
        db.close()


def test_directory_tree_path_missing(tmp_path: Path) -> None:
    _index(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_directory_tree(db, path="pkg/missing")
        assert "No directory matches" in out
    finally:
        db.close()
