from src.tests.python_parser._assertions import (
    assert_reference_shape,
    assert_symbol_references_invariants,
)


def test_import_alias_bindings(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("imports_aliases.py")
    symbols, references = python_parser.parse(10, file_bytes)

    assert len(symbols) == 0
    assert len(references) == 0
    assert python_parser._import_qn["operating_system"] == "os"
    assert python_parser._import_qn["P"] == "pathlib.Path"
    assert python_parser._import_qn["t"] == "collections.defaultdict"


def test_relative_import_binding_rewrites_reference(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ref_qn_relative_import.py")
    _, references = python_parser.parse(53, file_bytes, module_qn="pkg.sub.caller")

    assert any(
        r["ref_kind"] == "call" and r["ref_symbol_qualified_name"] == "pkg.sub.sib.Foo"
        for r in references
    )


def test_multi_import_bindings(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("imports_multiple.py")
    symbols, references = python_parser.parse(11, file_bytes)

    assert len(symbols) == 0
    assert len(references) == 0
    assert python_parser._import_qn["Path"] == "pathlib.Path"
    assert python_parser._import_qn["PurePath"] == "pathlib.PurePath"
    assert "os" in python_parser._ref_root_module
    assert "sys" in python_parser._ref_root_module


def test_non_stdlib_import_call_records_rewritten_qn(python_parser) -> None:
    source = b"from sqlglot import Exp\n\n\ndef run() -> None:\n    Exp()\n"
    symbols, references = python_parser.parse(99, source, module_qn="app")

    assert any(s["qualified_name"] == "app.run" for s in symbols)
    assert any(
        r["ref_kind"] == "call" and r["ref_symbol_qualified_name"] == "sqlglot.Exp"
        for r in references
    )


def test_references_dotted_calls_and_chained_attributes(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("references_dotted_and_chained.py")
    symbols, references = python_parser.parse(12, file_bytes)

    assert len(symbols) == 1
    assert_symbol_references_invariants(references)
    for r in references:
        assert_reference_shape(r, expected_file_id=12)

    assert not any(
        r["ref_kind"] == "call" and r["ref_symbol_name"] == "pkgutil.walk_packages"
        for r in references
    )
    assert not any(r["ref_symbol_name"].startswith("obj.") for r in references)
