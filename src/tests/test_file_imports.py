from pathlib import Path

from src.codeparse_mcp.file_imports import get_file_imports
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


def test_file_imports_none_when_file_has_no_imports(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("def run() -> None:\n    pass\n", encoding="utf-8")
    db = CodeDB(tmp_path)
    try:
        CodeProcessor(db, tmp_path).process()
        out = get_file_imports(db, "mod.py")
        assert "Total Imports: 0" in out
        assert "Total Lines:" not in out
        assert "File:" not in out
        assert "## Imports" not in out
        assert "No imports found." in out
        assert "## Symbols" not in out
    finally:
        db.close()


def test_file_imports_omits_symbols(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        out = get_file_imports(db, "pkg/mod.py")
        assert "## Symbols" not in out
        assert "pkg.mod.early" not in out
        assert "pkg.mod.late" not in out
        assert "File:" not in out
        assert "Total Lines:" not in out
        assert "Total Imports: 2" in out
        assert "## Imports" not in out
        assert "L1   from pkg.other import helper" in out
        assert "L8   from pkg.late import late_thing" in out
    finally:
        db.close()
