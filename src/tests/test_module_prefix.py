"""Module names start at the outermost package, not a non-package parent like src."""

from pathlib import Path

from src.codeparse_mcp.import_relations import get_import_relations
from src.db import CodeDB
from src.processor import CodeProcessor


def _index(root: Path) -> CodeDB:
    (root / ".gitignore").write_text("# test\n", encoding="utf-8")
    db = CodeDB(root)
    CodeProcessor(db, root).process()
    return db


def test_src_layout_strips_non_package_prefix(tmp_path: Path) -> None:
    src = tmp_path / "src" / "fundamentals"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "xxx.py").write_text("def y() -> int:\n    return 1\n", encoding="utf-8")
    (tmp_path / "use.py").write_text(
        "from fundamentals.xxx import y\n\n\ndef run() -> int:\n    return y()\n",
        encoding="utf-8",
    )
    db = _index(tmp_path)
    try:
        row = db.connection.execute(
            "SELECT normalized_path FROM files WHERE path = ?",
            ("src/fundamentals/xxx.py",),
        ).fetchone()
        assert row["normalized_path"] == "fundamentals.xxx"
        symbol = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE name = 'y'"
        ).fetchone()
        assert symbol["qualified_name"] == "fundamentals.xxx.y"
        out = get_import_relations(db, "fundamentals.xxx", include_tests=False)
        assert "fundamentals.xxx.y (" in out
        assert "use.py" in out
        assert "• " in out
    finally:
        db.close()


def test_root_package_keeps_its_prefix(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("def helper() -> None:\n    pass\n", encoding="utf-8")
    db = _index(tmp_path)
    try:
        row = db.connection.execute(
            "SELECT normalized_path FROM files WHERE path = ?",
            ("pkg/mod.py",),
        ).fetchone()
        assert row["normalized_path"] == "pkg.mod"
        symbol = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE name = 'helper'"
        ).fetchone()
        assert symbol["qualified_name"] == "pkg.mod.helper"
    finally:
        db.close()


def test_relative_import_under_src_omits_src(tmp_path: Path) -> None:
    package = tmp_path / "src" / "fundamentals"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "sib.py").write_text("class Foo:\n    pass\n", encoding="utf-8")
    (package / "caller.py").write_text(
        "from .sib import Foo\n\n\ndef make() -> Foo:\n    return Foo()\n",
        encoding="utf-8",
    )
    db = _index(tmp_path)
    try:
        out = get_import_relations(db, "fundamentals.sib", include_tests=False)
        assert "• src/fundamentals/caller.py" in out
        assert "• fundamentals.sib.Foo (" in out
    finally:
        db.close()


def test_path_with_no_package_keeps_every_directory(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("def main() -> None:\n    pass\n", encoding="utf-8")
    db = _index(tmp_path)
    try:
        row = db.connection.execute(
            "SELECT normalized_path FROM files WHERE path = ?",
            ("src/app.py",),
        ).fetchone()
        assert row["normalized_path"] == "src.app"
    finally:
        db.close()
