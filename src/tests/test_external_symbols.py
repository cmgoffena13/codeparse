from pathlib import Path

from src.codeparse_mcp.directory_tree import get_directory_tree
from src.codeparse_mcp.entry_points import get_entry_points
from src.codeparse_mcp.search_symbols import search_symbols
from src.codeparse_mcp.symbol import get_symbol
from src.db import (
    EXTERNAL_PACKAGES_FILE_ID,
    EXTERNAL_PACKAGES_PATH,
    CodeDB,
    _ref_qn_is_indexed,
)
from src.processor import CodeProcessor


def test_ref_qn_is_indexed_matches_module_and_children() -> None:
    indexed = {"pkg", "pkg.mod", "other"}
    assert _ref_qn_is_indexed("pkg", indexed)
    assert _ref_qn_is_indexed("pkg.mod", indexed)
    assert _ref_qn_is_indexed("pkg.mod.Helper", indexed)
    assert _ref_qn_is_indexed("pkg.sibling.Foo", indexed)
    assert not _ref_qn_is_indexed("sqlglot.Exp", indexed)
    assert not _ref_qn_is_indexed("pkgx.mod", indexed)


def test_delete_external_ledger_rows_drops_pairs_and_orphan_stubs(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    db = CodeDB(tmp_path)
    db.connection.execute(
        """
        INSERT INTO symbols
        (id, file_id, parent_id, name, parent, qualified_name, kind, line_start,
         line_end, line_count, signature, docstring, modifiers, language,
         is_test, is_inherited)
        VALUES
        (1, ?, NULL, 'Exp', 'sqlglot', 'sqlglot.Exp', 'external', 0, 0, 0, '', NULL, NULL,
         'python', 0, 0),
        (2, ?, NULL, 'path', 'os', 'os.path', 'external', 0, 0, 0, '', NULL, NULL,
         'python', 0, 0)
        """,
        (EXTERNAL_PACKAGES_FILE_ID, EXTERNAL_PACKAGES_FILE_ID),
    )
    db.connection.executemany(
        "INSERT INTO external_symbols (file_id, qualified_name) VALUES (?, ?)",
        [(10, "sqlglot.Exp"), (11, "os.path"), (10, "os.path")],
    )
    db.connection.commit()
    db._delete_external_ledger_rows([(10, "sqlglot.Exp"), (11, "os.path")])
    leftover = {
        (row["file_id"], row["qualified_name"])
        for row in db.connection.execute("SELECT file_id, qualified_name FROM external_symbols")
    }
    assert leftover == {(10, "os.path")}
    stub_qns = {
        row["qualified_name"]
        for row in db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE file_id = ?",
            (EXTERNAL_PACKAGES_FILE_ID,),
        )
    }
    assert stub_qns == {"os.path"}
    db.close()


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
    overview = get_entry_points(db)
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

    out = get_symbol(db, "sqlglot.Exp", include_tests=False)
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
        "import collections.abc\nfrom collections import abc\n\n"
        "def run() -> None:\n    abc\n    collections.abc\n",
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


def test_unreferenced_external_import_does_not_create_stub(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from sqlglot import Exp\n\ndef run() -> None:\n    pass\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)
    assert (
        db.connection.execute(
            "SELECT COUNT(*) AS c FROM symbols WHERE qualified_name = 'sqlglot.Exp'"
        ).fetchone()["c"]
        == 0
    )
    assert (
        db.connection.execute(
            "SELECT COUNT(*) AS c FROM external_symbols WHERE qualified_name = 'sqlglot.Exp'"
        ).fetchone()["c"]
        == 0
    )
    db.close()


def test_referenced_external_writes_ledger_row(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from sqlglot import Exp\n\ndef run() -> None:\n    Exp()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)
    rows = list(
        db.connection.execute(
            """
            SELECT es.qualified_name, f.path
            FROM external_symbols AS es
            INNER JOIN files AS f ON f.id = es.file_id
            WHERE es.qualified_name = 'sqlglot.Exp'
            """
        )
    )
    assert len(rows) == 1
    assert rows[0]["path"] == "app.py"
    db.close()


def test_shared_external_stub_survives_when_one_file_drops_ref(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text(
        "from sqlglot import Exp\n\ndef run_a() -> None:\n    Exp()\n",
        encoding="utf-8",
    )
    b.write_text(
        "from sqlglot import Exp\n\ndef run_b() -> None:\n    Exp()\n",
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
    assert (
        db.connection.execute(
            "SELECT COUNT(*) AS c FROM external_symbols WHERE qualified_name = 'sqlglot.Exp'"
        ).fetchone()["c"]
        == 2
    )

    a.write_text("def run_a() -> None:\n    pass\n", encoding="utf-8")
    processor.process()
    assert (
        db.connection.execute(
            "SELECT COUNT(*) AS c FROM symbols WHERE qualified_name = 'sqlglot.Exp'"
        ).fetchone()["c"]
        == 1
    )
    assert (
        db.connection.execute(
            "SELECT COUNT(*) AS c FROM external_symbols WHERE qualified_name = 'sqlglot.Exp'"
        ).fetchone()["c"]
        == 1
    )
    db.close()


def test_file_delete_orphans_external_stub(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    app = tmp_path / "app.py"
    app.write_text(
        "from sqlglot import Exp\n\ndef run() -> None:\n    Exp()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    processor = CodeProcessor(db, tmp_path)
    processor.process(full=True)
    app.unlink()
    processor.process()
    assert (
        db.connection.execute(
            "SELECT COUNT(*) AS c FROM symbols WHERE qualified_name = 'sqlglot.Exp'"
        ).fetchone()["c"]
        == 0
    )
    assert (
        db.connection.execute(
            "SELECT COUNT(*) AS c FROM external_symbols WHERE qualified_name = 'sqlglot.Exp'"
        ).fetchone()["c"]
        == 0
    )
    db.close()
