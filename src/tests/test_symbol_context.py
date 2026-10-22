"""Tests for get_symbol_context and get_symbol_references MCP queries."""

from pathlib import Path

from src.codeparse_mcp.symbol_context import get_symbol_context
from src.codeparse_mcp.symbol_references import get_symbol_references
from src.db import CodeDB
from src.processor import CodeProcessor


def _index(tmp_path: Path) -> Path:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text(
        "def helper() -> int:\n"
        "    return 1\n"
        "\n"
        "\n"
        "class Worker:\n"
        "    def run(self) -> int:\n"
        "        return helper()\n",
        encoding="utf-8",
    )
    (pkg / "user.py").write_text(
        "from pkg.target import helper\n\nhelper()\n\ndef run() -> int:\n    return helper()\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_target.py").write_text(
        "from pkg.target import helper\n\n\ndef test_helper() -> None:\n    assert helper() == 1\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    db.close()
    return tmp_path


def test_symbol_context_definition_only(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        out = get_symbol_context(db, "pkg.target.helper", include_tests=False)
        assert "## Code Definition" not in out
        assert "Legend:" not in out
        assert "Kind:" not in out
        assert "Lines:" not in out
        assert "## References (3)" in out
        assert "Calls: 3" in out
        assert "Test References" not in out
        with_tests = get_symbol_context(db, "pkg.target.helper", include_tests=True)
        assert "## Test References (1)" in with_tests
        assert "Calls: 1" in with_tests
        assert with_tests.index("## References") < with_tests.index("## Test References")
        assert "Access:" not in out
        assert "Type Annotations:" not in out
        assert "Parent:" not in out
        assert "Language:" not in out
        assert "Symbol:" not in out
        assert out.index("File:") < out.index("def helper()")
        assert "pkg/user.py" not in out
        assert "tests/test_target.py" not in out
        assert "## Calls" not in out

        method = get_symbol_context(db, "pkg.target.Worker.run", include_tests=False)
        assert "Parent:" not in method
        assert "Language:" not in method
        assert "Kind:" not in method
        assert "Lines:" not in method
        assert "Symbol:" not in method
        assert method.index("File:") < method.index("def run(")
    finally:
        db.close()


def test_symbol_context_marks_inherited_file(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "base.py").write_text(
        "class GenericContext:\n    def plan(self):\n        return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "child.py").write_text(
        "from base import GenericContext\n"
        "\n"
        "\n"
        "class Context(GenericContext):\n"
        "    def apply(self):\n"
        "        return self.plan()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)
    try:
        inherited = get_symbol_context(db, "child.Context.plan", include_tests=False)
        defined = get_symbol_context(db, "base.GenericContext.plan", include_tests=False)
        assert "File: base.py (inherited)" in inherited
        assert "File: base.py (inherited)" not in defined
        assert "File: base.py\n" in defined
    finally:
        db.close()


def test_symbol_references_lists_calls_with_counts(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        out = get_symbol_references(db, "pkg.target.helper", include_tests=False)
        assert "References of" not in out
        assert "Legend:" not in out
        assert "total" not in out
        assert "pkg/user.py" in out
        assert "tests/test_target.py" not in out
        assert "## Calls" in out
        assert "  • pkg.user.run" in out
        assert "  • L3  (no symbol)" in out
        assert "L5" not in out
        assert "pkg/user.py:" not in out
        assert "(" in out  # kind section counts
    finally:
        db.close()


def test_symbol_references_include_tests(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        out = get_symbol_references(db, "pkg.target.helper", include_tests=True)
        assert "pkg/user.py" in out
        assert "tests/test_target.py" in out
    finally:
        db.close()


def test_symbol_references_none(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        out = get_symbol_references(db, "pkg.target.missing", include_tests=False)
        assert out == "No references to pkg.target.missing were found."
    finally:
        db.close()
