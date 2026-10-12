from src.tests.python_parser._assertions import (
    assert_imports_invariants,
    assert_reference_shape,
    assert_symbol_references_invariants,
)


def test_imports_spot_checks_from_fixture_file(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("file.py")
    _, imports, _ = python_parser.parse(1, file_bytes)

    assert len(imports) == 3
    assert_imports_invariants(imports)

    assert any(i["import_path"] == "json" and i["imported_symbol"] == "" for i in imports)
    assert any(i["import_path"] == "pathlib" and i["imported_symbol"] == "Path" for i in imports)
    assert any(i["import_type"] == "relative" for i in imports)


def test_relative_import_path_is_the_resolved_module(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ref_qn_relative_import.py")
    _, imports, _ = python_parser.parse(53, file_bytes, module_qn="pkg.sub.caller")

    assert any(
        i["import_type"] == "relative"
        and i["import_path"] == "pkg.sub.sib"
        and i["imported_symbol"] == "Foo"
        and i["signature"] == "from .sib import Foo"
        for i in imports
    )


def test_imports_aliases(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("imports_aliases.py")
    symbols, imports, references = python_parser.parse(10, file_bytes)

    assert len(symbols) == 0
    assert len(references) == 0
    assert len(imports) == 3
    assert_imports_invariants(imports)

    # import os as operating_system -> imported_symbol empty, alias set
    assert any(
        i["import_path"] == "os" and i["imported_symbol"] == "" and i["alias"] == "operating_system"
        for i in imports
    )
    # from pathlib import Path as P
    assert any(
        i["import_path"] == "pathlib" and i["imported_symbol"] == "Path" and i["alias"] == "P"
        for i in imports
    )
    assert any(
        i["import_path"] == "collections"
        and i["imported_symbol"] == "defaultdict"
        and i["alias"] == "t"
        for i in imports
    )


def test_imports_multiple_in_one_statement(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("imports_multiple.py")
    symbols, imports, references = python_parser.parse(11, file_bytes)

    assert len(symbols) == 0
    assert len(references) == 0
    assert len(imports) == 4
    assert_imports_invariants(imports)

    assert any(i["import_path"] == "os" and i["imported_symbol"] == "" for i in imports)
    assert any(i["import_path"] == "sys" and i["imported_symbol"] == "" for i in imports)
    assert any(i["import_path"] == "pathlib" and i["imported_symbol"] == "Path" for i in imports)
    assert any(
        i["import_path"] == "pathlib" and i["imported_symbol"] == "PurePath" for i in imports
    )


def test_references_dotted_calls_and_chained_attributes(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("references_dotted_and_chained.py")
    symbols, imports, references = python_parser.parse(12, file_bytes)

    assert len(symbols) == 1
    assert len(imports) == 1
    assert len(references) == 4
    assert_symbol_references_invariants(references)
    for r in references:
        assert_reference_shape(r, expected_file_id=12)

    # stdlib calls are filtered
    assert not any(
        r["ref_kind"] == "call" and r["ref_symbol_name"] == "pkgutil.walk_packages"
        for r in references
    )
    assert any(r["ref_kind"] == "access" and r["ref_symbol_name"] == "obj.a.b" for r in references)
    assert any(
        r["ref_kind"] == "access" and r["ref_symbol_name"] == "obj.m().n" for r in references
    )
    # Current behavior: obj.m() produces its own call reference (separate from access on obj.m().n)
    assert any(r["ref_kind"] == "call" and r["ref_symbol_name"] == "obj.m" for r in references)
