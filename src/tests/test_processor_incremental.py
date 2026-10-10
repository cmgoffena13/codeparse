"""Integration tests: CodeProcessor + DB idempotency across repeated runs."""

import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.db import CodeDB
from src.processor import CodeProcessor
from src.utils import db_path_for_index_root

# Nested package + class + method + call so an unchanged outer def must still
# push the parser stack (regression for snapshot/re-parse churn).
NESTED_PKG_MOD = '''"""nested pkg module."""
class Outer:
    def method(self):
        x = 1
        self.method()
'''


def _db_counts(tmp: Path) -> dict:
    db_file = db_path_for_index_root(tmp)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        dirs = conn.execute("SELECT id, path FROM directories ORDER BY id").fetchall()
        return {
            "directories": [(r["id"], r["path"]) for r in dirs],
            "files": conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"],
            "symbols": conn.execute("SELECT COUNT(*) AS c FROM symbols").fetchone()["c"],
            "symbol_references": conn.execute(
                "SELECT COUNT(*) AS c FROM symbol_references"
            ).fetchone()["c"],
            "imports": conn.execute("SELECT COUNT(*) AS c FROM imports").fetchone()["c"],
            "symbol_count_sum": conn.execute(
                "SELECT COALESCE(SUM(symbol_count), 0) AS s FROM files"
            ).fetchone()["s"],
        }
    finally:
        conn.close()


def _write_nested_fixture(tmp: Path) -> None:
    # `path_spec_for_indexing` requires a root `.gitignore` to exist.
    (tmp / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    pkg = tmp / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "mod.py").write_text(NESTED_PKG_MOD, encoding="utf-8")


def test_two_full_indexes_identical_counts(tmp_path: Path) -> None:
    _write_nested_fixture(tmp_path)

    db1 = CodeDB(tmp_path)
    CodeProcessor(db1, tmp_path).process(full=True)
    first = _db_counts(tmp_path)

    db2 = CodeDB(tmp_path)
    CodeProcessor(db2, tmp_path).process(full=True)
    second = _db_counts(tmp_path)

    assert first == second
    assert first["files"] >= 1
    assert first["symbols"] >= 1
    assert first["symbol_references"] >= 1
    assert first["symbol_count_sum"] == first["symbols"]


def test_full_then_incremental_identical_counts(tmp_path: Path) -> None:
    _write_nested_fixture(tmp_path)

    db1 = CodeDB(tmp_path)
    CodeProcessor(db1, tmp_path).process(full=True)
    after_full = _db_counts(tmp_path)

    db2 = CodeDB(tmp_path)
    CodeProcessor(db2, tmp_path).process(full=False)
    after_inc = _db_counts(tmp_path)

    assert after_full == after_inc


def test_incremental_mutation_updates_counts_and_deletes(tmp_path: Path) -> None:
    _write_nested_fixture(tmp_path)

    db1 = CodeDB(tmp_path)
    CodeProcessor(db1, tmp_path).process(full=True)
    before = _db_counts(tmp_path)

    # Mutate file: remove the call and add a few lines
    mod = tmp_path / "pkg" / "mod.py"
    mod.write_text(
        '''"""nested pkg module."""
class Outer:
    def method(self):
        x = 1
        y = 2
        z = 3
        return x + y + z
''',
        encoding="utf-8",
    )

    db2 = CodeDB(tmp_path)
    CodeProcessor(db2, tmp_path).process(full=True)
    after = _db_counts(tmp_path)

    # Files/symbols should remain stable; references should drop because the call is removed.
    assert after["files"] == before["files"]
    assert after["symbols"] == before["symbols"]
    assert after["symbol_references"] < before["symbol_references"]


def test_same_name_symbols_in_two_files_both_survive(tmp_path: Path) -> None:
    """Module-prefixed QNs prevent INSERT OR REPLACE collisions across files."""
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def main():\n    return 1\n", encoding="utf-8")

    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    rows = db.connection.execute(
        "SELECT qualified_name FROM symbols WHERE kind = 'function' ORDER BY qualified_name"
    ).fetchall()
    qns = [r["qualified_name"] for r in rows]
    assert qns == ["a.main", "b.main"]
    assert db.connection.execute("SELECT COUNT(*) AS c FROM symbols").fetchone()["c"] == 2


def test_cross_file_import_call_joins_after_resolve(tmp_path: Path) -> None:
    """from lib import target; target() joins to lib.target after resolve."""
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "lib.py").write_text("def target():\n    pass\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from lib import target\n\ndef run():\n    target()\n",
        encoding="utf-8",
    )

    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    row = db.connection.execute(
        """
        SELECT sr.ref_symbol_qualified_name, sr.ref_symbol_id, s.qualified_name
        FROM symbol_references AS sr
        INNER JOIN symbols AS s ON s.id = sr.ref_symbol_id
        WHERE sr.ref_kind = 'call' AND sr.ref_symbol_qualified_name = 'lib.target'
        """
    ).fetchone()
    assert row is not None
    assert row["qualified_name"] == "lib.target"


def test_same_line_duplicate_calls_index_without_integrity_error(
    tmp_path: Path,
) -> None:
    """Two calls on one line must get distinct reference ids through resolve."""
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text(
        "def target():\n    pass\n\ndef run():\n    target(); target()\n",
        encoding="utf-8",
    )

    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    rows = db.connection.execute(
        """
        SELECT source_line, source_column, id
        FROM symbol_references
        WHERE ref_kind = 'call' AND ref_symbol_qualified_name = 'mod.target'
        ORDER BY source_column
        """
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["source_line"] == rows[1]["source_line"]
    assert rows[0]["source_column"] != rows[1]["source_column"]
    assert rows[0]["id"] != rows[1]["id"]


def test_extensionless_broken_symlink_is_not_a_skipped_source(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("all:\n", encoding="utf-8")
    (tmp_path / "customers").symlink_to("../packages/customers")

    db = CodeDB(tmp_path)
    processor = CodeProcessor(db, tmp_path)
    processor.process(full=True)
    names = {row["name"] for row in db.connection.execute("SELECT name FROM files")}
    assert {"mod.py", "Makefile"} <= names
    assert "customers" not in names


def test_concurrent_run_query_does_not_raise(tmp_path: Path) -> None:
    """MCP may run tools in parallel; shared SQLite must be serialized."""
    _write_nested_fixture(tmp_path)
    db = CodeDB(tmp_path)
    processor = CodeProcessor(db, tmp_path)
    processor.process(full=True)

    def worker() -> int:
        return processor.run_query(
            lambda conn: conn.connection.execute("SELECT COUNT(*) AS c FROM symbols").fetchone()[
                "c"
            ]
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker) for _ in range(8)]
        results = [f.result() for f in as_completed(futures)]

    assert len(results) == 8
    assert all(isinstance(n, int) for n in results)
