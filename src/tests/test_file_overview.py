"""Tests for get_file_overview MCP query."""

from pathlib import Path

from src.codeparse_mcp.file_overview import get_file_overview
from src.db import CodeDB
from src.processor import CodeProcessor


def _index(tmp_path: Path) -> Path:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(
        "from pkg.other import helper\n"
        "\n"
        "\n"
        "def early() -> None:\n"
        "    pass\n"
        "\n"
        "\n"
        "from pkg.late import late_thing\n"
        "\n"
        "\n"
        "def late() -> int:\n"
        "    return late_thing()\n",
        encoding="utf-8",
    )
    (pkg / "other.py").write_text("def helper() -> None:\n    pass\n", encoding="utf-8")
    (pkg / "late.py").write_text("def late_thing() -> int:\n    return 1\n", encoding="utf-8")
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    db.close()
    return tmp_path


def test_file_overview_includes_import_and_symbol_line_numbers(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        out = get_file_overview(db, "pkg/mod.py")
        assert "Legend: L = Line" in out
        assert "Language:" not in out
        assert out.index("File:") < out.index("Lines:")
        # Padded gutters (file has 13 lines → width 2).
        assert "L1   from pkg.other import helper" in out
        assert "L8   from pkg.late import late_thing" in out
        assert "L4-5  function  pkg.mod.early" in out
        assert "L11-12  function  pkg.mod.late" in out
        assert "Sig:" not in out
        assert "Doc:" not in out
        assert "(2L)" not in out
    finally:
        db.close()


def test_file_overview_labels_property_methods(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text(
        "class Box:\n"
        "    @property\n"
        "    def size(self) -> int:\n"
        "        return 1\n"
        "\n"
        "    def grow(self) -> None:\n"
        "        pass\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    try:
        CodeProcessor(db, tmp_path).process()
        out = get_file_overview(db, "mod.py")
        assert "property  mod.Box.size" in out
        assert "method  mod.Box.grow" in out
    finally:
        db.close()
