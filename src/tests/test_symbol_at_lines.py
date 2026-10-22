"""Tests for get_symbol_at_lines."""

from pathlib import Path

from src.codeparse_mcp.symbol_at_lines import get_symbol_at_lines
from src.codeparse_mcp.symbol_context import get_symbol_context
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
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    db.close()
    return tmp_path


def _with_symbol_header(body: str, qualified_name: str) -> str:
    rest = body.split("\n", 1)[1]
    return f"Symbol: {qualified_name}\n{rest}"


def test_symbol_at_lines_picks_the_tightest_span(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        assert get_symbol_at_lines(
            db, "pkg/target.py", 1, None, include_tests=False
        ) == _with_symbol_header(
            get_symbol_context(db, "pkg.target.helper", include_tests=False), "pkg.target.helper"
        )
        shown = get_symbol_at_lines(db, "pkg/target.py", 1, None, include_tests=True)
        assert "Test References" in shown
        assert get_symbol_at_lines(
            db, "pkg/target.py", 7, None, include_tests=False
        ) == _with_symbol_header(
            get_symbol_context(db, "pkg.target.Worker.run", include_tests=False),
            "pkg.target.Worker.run",
        )
        assert get_symbol_at_lines(
            db, "pkg/target.py", 6, 7, include_tests=False
        ) == _with_symbol_header(
            get_symbol_context(db, "pkg.target.Worker.run", include_tests=False),
            "pkg.target.Worker.run",
        )
        assert get_symbol_at_lines(
            db, "pkg/target.py", 5, 7, include_tests=False
        ) == _with_symbol_header(
            get_symbol_context(db, "pkg.target.Worker", include_tests=False), "pkg.target.Worker"
        )
        assert get_symbol_at_lines(
            db, "pkg/target.py", 2, 3, include_tests=False
        ) == _with_symbol_header(
            get_symbol_context(db, "pkg.target.helper", include_tests=False), "pkg.target.helper"
        )
        assert get_symbol_at_lines(db, "pkg/target.py", 2, 5, include_tests=False) == (
            "Multiple symbols found:\n  • pkg.target.helper — L1-2\n  • pkg.target.Worker — L5-7\n"
        )
        assert "No symbol" in get_symbol_at_lines(db, "pkg/target.py", 4, None, include_tests=False)
    finally:
        db.close()


def test_symbol_at_lines_marks_inherited_when_multiple_hits(tmp_path: Path) -> None:
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
        shown = get_symbol_at_lines(db, "base.py", 2, 3, include_tests=False)
        assert shown == (
            "Multiple symbols found:\n"
            "  • base.GenericContext.plan — L2-3\n"
            "  • child.Context.plan — L2-3 (inherits)\n"
        )
    finally:
        db.close()
