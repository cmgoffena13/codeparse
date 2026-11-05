from pathlib import Path

from src.codeparse_mcp.directory_tree import get_directory_tree
from src.codeparse_mcp.project_overview import get_project_overview
from src.codeparse_mcp.search_symbols import search_symbols
from src.codeparse_mcp.symbol_context import get_symbol_context
from src.db import EXTERNAL_PACKAGES_FILE_ID, EXTERNAL_PACKAGES_PATH, CodeDB
from src.processor import CodeProcessor


def test_external_import_stub_joins_symbol_references(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from sqlglot import Exp\n\ndef run() -> None:\n    Exp()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    stub = db.connection.execute(
        """
        SELECT id, file_id, kind, name, parent
        FROM symbols
        WHERE qualified_name = 'sqlglot.Exp'
        """
    ).fetchone()
    assert stub is not None
    assert stub["file_id"] == EXTERNAL_PACKAGES_FILE_ID
    assert stub["kind"] == "external"
    assert stub["name"] == "Exp"
    assert stub["parent"] == "sqlglot"

    row = db.connection.execute(
        """
        SELECT sr.ref_symbol_id, s.qualified_name, s.file_id
        FROM symbol_references AS sr
        INNER JOIN symbols AS s ON s.id = sr.ref_symbol_id
        WHERE sr.ref_kind = 'call' AND sr.ref_symbol_qualified_name = 'sqlglot.Exp'
        """
    ).fetchone()
    assert row is not None
    assert row["ref_symbol_id"] == stub["id"]
    assert row["file_id"] == EXTERNAL_PACKAGES_FILE_ID
    db.close()


def test_in_repo_module_wins_over_external_stub(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "sqlglot.py").write_text("def Exp() -> None:\n    pass\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from sqlglot import Exp\n\ndef run() -> None:\n    Exp()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    rows = list(
        db.connection.execute(
            """
            SELECT file_id, qualified_name
            FROM symbols
            WHERE qualified_name = 'sqlglot.Exp'
            """
        )
    )
    assert len(rows) == 1
    assert rows[0]["file_id"] != EXTERNAL_PACKAGES_FILE_ID
    db.close()


def test_orphan_external_stub_is_removed_when_import_gone(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    app = tmp_path / "app.py"
    app.write_text(
        "from sqlglot import Exp\n\ndef run() -> None:\n    Exp()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    processor = CodeProcessor(db, tmp_path)
    processor.process(full=True)
    assert (
        db.connection.execute(
            "SELECT COUNT(*) AS c FROM symbols WHERE qualified_name = 'sqlglot.Exp'"
        ).fetchone()["c"]
        == 1
    )

    app.write_text("def run() -> None:\n    pass\n", encoding="utf-8")
    processor.process()
    assert (
        db.connection.execute(
            "SELECT COUNT(*) AS c FROM symbols WHERE qualified_name = 'sqlglot.Exp'"
        ).fetchone()["c"]
        == 0
    )
    assert (
        db.connection.execute(
            """
            SELECT COUNT(*) AS c FROM symbol_references
            WHERE ref_symbol_qualified_name = 'sqlglot.Exp'
            """
        ).fetchone()["c"]
        == 0
    )
    db.close()


def test_directory_tree_and_overview_hide_external_packages(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from sqlglot import Exp\n\ndef run() -> None:\n    Exp()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    tree = get_directory_tree(db, None)
    overview = get_project_overview(db)
    assert EXTERNAL_PACKAGES_PATH not in tree
    assert EXTERNAL_PACKAGES_PATH not in overview
    db.close()


def test_get_symbol_reports_external_stub_without_source(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from sqlglot import Exp\n\ndef run() -> None:\n    Exp()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    out = get_symbol_context(db, "sqlglot.Exp", include_tests=False)
    assert f"File: {EXTERNAL_PACKAGES_PATH}" in out
    assert "(external stub; no source in workspace)" in out
    assert "could not read source file" not in out
    db.close()


def test_search_symbols_finds_external_stub(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from sqlglot import Exp\n\ndef run() -> None:\n    Exp()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    out = search_symbols(db, "Exp", limit=20, include_tests=False)
    assert EXTERNAL_PACKAGES_PATH in out
    assert "sqlglot.Exp" in out
    db.close()


def test_module_and_from_import_same_qn_insert_one_stub(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "import collections.abc\nfrom collections import abc\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    rows = list(
        db.connection.execute(
            """
            SELECT file_id, kind, qualified_name
            FROM symbols
            WHERE qualified_name = 'collections.abc'
            """
        )
    )
    assert len(rows) == 1
    assert rows[0]["file_id"] == EXTERNAL_PACKAGES_FILE_ID
    db.close()
