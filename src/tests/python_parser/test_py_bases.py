"""Resolved class bases land in ``base_qualified_names`` and ``symbol_bases``."""

from src.tests.python_parser._assertions import index_symbols


def _bases(symbols: list[dict], name: str) -> list[str]:
    return index_symbols(symbols)[name]["base_qualified_names"]


def test_same_module_base_is_qualified(python_parser) -> None:
    source = b"class Parent:\n    pass\n\nclass Child(Parent):\n    pass\n"
    symbols, _, _ = python_parser.parse(1, source, module_qn="pkg.mod")
    assert _bases(symbols, "pkg.mod.Child") == ["pkg.mod.Parent"]


def test_imported_base_uses_import_qn(python_parser) -> None:
    source = b"from abc import ABC\n\nclass Foo(ABC):\n    pass\n"
    symbols, _, _ = python_parser.parse(1, source, module_qn="pkg.mod")
    assert _bases(symbols, "pkg.mod.Foo") == ["abc.ABC"]


def test_aliased_base_uses_original_qn(python_parser) -> None:
    source = b"from pkg.other import Parent as P\n\nclass Child(P):\n    pass\n"
    symbols, _, _ = python_parser.parse(1, source, module_qn="pkg.mod")
    assert _bases(symbols, "pkg.mod.Child") == ["pkg.other.Parent"]


def test_subscript_base_peels_to_generic(python_parser) -> None:
    source = (
        b"from typing import Generic, TypeVar\n"
        b"T = TypeVar('T')\n\n"
        b"class Foo(Generic[T]):\n"
        b"    pass\n"
    )
    symbols, _, _ = python_parser.parse(1, source, module_qn="pkg.mod")
    assert _bases(symbols, "pkg.mod.Foo") == ["typing.Generic"]


def test_base_only_change_rewrites_symbol_bases(python_parser, tmp_db) -> None:
    first = b"class Parent:\n    pass\n\nclass Other:\n    pass\n\nclass Child(Parent):\n    pass\n"
    second = b"class Parent:\n    pass\n\nclass Other:\n    pass\n\nclass Child(Other):\n    pass\n"
    symbols, imports, refs = python_parser.parse(1, first, module_qn="pkg.mod")
    tmp_db.connection.execute(
        """
        INSERT INTO files (id, name, path, normalized_path, content_hash)
        VALUES (1, 'mod.py', 'pkg/mod.py', 'pkg.mod', 'hash')
        """
    )
    tmp_db.bulk_insert(
        {
            "directories": [],
            "files": [],
            "entry_points": [],
            "symbols": symbols,
            "imports": imports,
            "symbol_references": refs,
        }
    )

    unchanged, _, _ = python_parser.parse(1, first, module_qn="pkg.mod")
    assert not any(s["name"] == "Child" for s in unchanged)

    changed, _, _ = python_parser.parse(1, second, module_qn="pkg.mod")
    child = next(s for s in changed if s["name"] == "Child")
    assert child["base_qualified_names"] == ["pkg.mod.Other"]

    tmp_db.bulk_insert(
        {
            "directories": [],
            "files": [],
            "entry_points": [],
            "symbols": changed,
            "imports": [],
            "symbol_references": [],
        }
    )
    rows = tmp_db.connection.execute(
        """
        SELECT sb.base_qualified_name
        FROM symbol_bases AS sb
        INNER JOIN symbols AS s ON s.id = sb.symbol_id
        WHERE s.qualified_name = 'pkg.mod.Child'
        """
    ).fetchall()
    assert [row["base_qualified_name"] for row in rows] == ["pkg.mod.Other"]
