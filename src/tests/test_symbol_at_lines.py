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


def test_symbol_at_lines_picks_the_tightest_span(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        assert get_symbol_at_lines(db, "pkg/target.py", 1) == get_symbol_context(
            db, "pkg.target.helper"
        )
        assert get_symbol_at_lines(db, "pkg/target.py", 7) == get_symbol_context(
            db, "pkg.target.Worker.run"
        )
        assert get_symbol_at_lines(db, "pkg/target.py", 6, 7) == get_symbol_context(
            db, "pkg.target.Worker.run"
        )
        assert get_symbol_at_lines(db, "pkg/target.py", 5, 7) == get_symbol_context(
            db, "pkg.target.Worker"
        )
        assert get_symbol_at_lines(db, "pkg/target.py", 2, 3) == get_symbol_context(
            db, "pkg.target.helper"
        )
        assert get_symbol_at_lines(db, "pkg/target.py", 2, 5) == (
            "Multiple symbols found:\n"
            "  • pkg.target.helper — lines 1-2\n"
            "  • pkg.target.Worker — lines 5-7\n"
        )
        assert "No symbol" in get_symbol_at_lines(db, "pkg/target.py", 4)
    finally:
        db.close()
