import tempfile
from pathlib import Path

from src.assigner import GlobalIDAssigner
from src.db import CodeDB
from src.parsers.factory import ParserFactory


def _parse_with_shared_db(file_id: int, first: bytes, second: bytes):
    """Parse twice against the same DB to exercise snapshot delete logic."""
    with tempfile.TemporaryDirectory() as d:
        db = CodeDB(Path(d))

        db.connection.execute(
            """
            INSERT INTO files (id, name, path, normalized_path, content_hash)
            VALUES (?, 'mod.py', 'mod.py', 'mod', 'hash')
            """,
            (file_id,),
        )
        assigner = GlobalIDAssigner(db)
        parser = ParserFactory.get_parser("python", assigner, db)

        a = parser.parse(file_id, first)
        db.bulk_insert(
            {
                "directories": [],
                "files": [],
                "entry_points": [],
                "symbols": a[0],
                "imports": a[1],
                "symbol_references": a[2],
            }
        )
        db.resolve_symbol_references()
        db.resolve_imports(0, 0)

        # New run against populated DB
        assigner2 = GlobalIDAssigner(db)
        parser2 = ParserFactory.get_parser("python", assigner2, db)
        b = parser2.parse(file_id, second)
        return a, b


def test_snapshot_deletes_removed_symbol_and_reference():
    first = b"""\
def a():
    b()

def b():
    return 1
"""
    second = b"""\
def a():
    return 1
"""

    (sym1, _imp1, ref1), (sym2, _imp2, ref2) = _parse_with_shared_db(99, first, second)

    assert len(sym1) == 2
    assert len(ref1) == 1
    # Second parse emits only deltas; unchanged symbol a() is not re-emitted.
    assert len(sym2) == 0
    assert len(ref2) == 0


def test_snapshot_allows_two_type_annotations_same_line_distinct_refs():
    first = b"""\
from pathlib import Path
from typing import Optional

def f(
    a: Optional[Path],
    b: Path,
):
    return a, b
"""

    (_sym1, _imp1, ref1), (_sym2, _imp2, ref2) = _parse_with_shared_db(100, first, first)

    assert len(ref1) == len(ref2)
    keys1 = {
        (
            r["ref_symbol_qualified_name"],
            r["ref_kind"],
            r["source_line"],
            r["source_column"],
        )
        for r in ref1
    }
    keys2 = {
        (
            r["ref_symbol_qualified_name"],
            r["ref_kind"],
            r["source_line"],
            r["source_column"],
        )
        for r in ref2
    }
    assert len(keys1) == len(ref1)
    assert len(keys2) == len(ref2)
