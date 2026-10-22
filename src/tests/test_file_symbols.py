from pathlib import Path

from src.codeparse_mcp.file_symbols import get_file_symbols
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


def test_file_symbols_omits_imports(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        out = get_file_symbols(db, "pkg/mod.py")
        assert "## Imports" not in out
        assert "## Symbols" not in out
        assert "from pkg.other import helper" not in out
        assert "from pkg.late import late_thing" not in out
        assert "File:" not in out
        assert out.index("Total Lines:") < out.index("Total Symbols:")
        assert "Total Symbols: 2" in out
        assert "L4-5  function  pkg.mod.early" in out
        assert "L11-12  function  pkg.mod.late" in out
        assert "Sig:" not in out
        assert "Doc:" not in out
        assert "(2L)" not in out
    finally:
        db.close()


def test_file_symbols_reports_missing_file(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        assert get_file_symbols(db, "pkg/missing.py") == "No file matches 'pkg/missing.py'."
        assert get_file_symbols(db, "") == "file_path is empty"
    finally:
        db.close()


def test_file_symbols_labels_property_methods(tmp_path: Path) -> None:
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
        out = get_file_symbols(db, "mod.py")
        assert "property  mod.Box.size" in out
        assert "method  mod.Box.grow" in out
    finally:
        db.close()
