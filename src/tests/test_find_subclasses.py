"""Tests for find_subclasses MCP query."""

from pathlib import Path

import pytest

from src.codeparse_mcp.find_subclasses import find_subclasses
from src.db import CodeDB
from src.processor import CodeProcessor


@pytest.fixture
def indexed_hierarchy(tmp_path: Path) -> Path:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "base.py").write_text(
        "class Parent:\n    pass\n\nclass Sibling(Parent):\n    pass\n\nclass Alone:\n    pass\n",
        encoding="utf-8",
    )
    (pkg / "child.py").write_text(
        "from pkg.base import Parent\n"
        "\n"
        "class Child(Parent):\n"
        "    pass\n"
        "\n"
        "class Grand(Child):\n"
        "    pass\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_parent.py").write_text(
        "from pkg.base import Parent\n\nclass TestChild(Parent):\n    pass\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    db.close()
    return tmp_path


def test_find_subclasses_lists_direct_children(indexed_hierarchy: Path) -> None:
    db = CodeDB(indexed_hierarchy)
    try:
        out = find_subclasses(db, "pkg.base.Parent")
        assert "Subclasses of pkg.base.Parent — 2 classes" in out
        assert "Legend:" not in out
        assert "pkg/base.py" in out
        assert "  • pkg.base.Sibling" in out
        assert "pkg/child.py" in out
        assert "  • pkg.child.Child" in out
        assert "pkg.child.Grand" not in out
        assert "pkg.base.Alone" not in out
        assert "tests/test_parent.py" not in out
    finally:
        db.close()


def test_find_subclasses_include_tests(indexed_hierarchy: Path) -> None:
    db = CodeDB(indexed_hierarchy)
    try:
        out = find_subclasses(db, "pkg.base.Parent", include_tests=True)
        assert "tests/test_parent.py" in out
        assert "  • tests.test_parent.TestChild" in out
        assert "3 classes" in out
    finally:
        db.close()


def test_find_subclasses_none(indexed_hierarchy: Path) -> None:
    db = CodeDB(indexed_hierarchy)
    try:
        out = find_subclasses(db, "pkg.base.Alone")
        assert out == "No subclasses of pkg.base.Alone found."
    finally:
        db.close()


def test_find_subclasses_missing_symbol(indexed_hierarchy: Path) -> None:
    db = CodeDB(indexed_hierarchy)
    try:
        out = find_subclasses(db, "pkg.base.Missing")
        assert out == "No subclasses of pkg.base.Missing found."
    finally:
        db.close()


def test_find_subclasses_empty_input(indexed_hierarchy: Path) -> None:
    db = CodeDB(indexed_hierarchy)
    try:
        assert "non-empty qualified_name" in find_subclasses(db, "  ")
    finally:
        db.close()
