from src.tests.python_parser._assertions import (
    assert_imports_invariants,
    assert_reference_shape,
    assert_symbol_references_invariants,
    assert_symbols_invariants,
    index_symbols,
)


def test_import_after_path_use_same_suite_still_filters_path_call(python_parser, fixture_bytes):
    """Import below Path(...) must still register before sibling refs (import-first walk)."""
    file_bytes = fixture_bytes("import_after_use_path.py")
    _, _, references = python_parser.parse(45, file_bytes)

    assert_symbol_references_invariants(references)
    assert not any(
        r["ref_kind"] == "call" and r["ref_symbol_name"].startswith("Path") for r in references
    )


def test_stdlib_import_and_literal_calls_filtered_from_references(python_parser, fixture_bytes):
    """Path(...) and str.join skipped; project name like files kept."""
    file_bytes = fixture_bytes("external_refs_filter.py")
    _, _, references = python_parser.parse(41, file_bytes)

    assert_symbol_references_invariants(references)
    assert not any(
        r["ref_kind"] == "call" and r["ref_symbol_name"].startswith("Path") for r in references
    )
    assert not any(r["ref_kind"] == "call" and "join" in r["ref_symbol_name"] for r in references)
    assert any(
        r["ref_kind"] == "call" and r["ref_symbol_name"] == "files.values" for r in references
    )


def test_self_attr_call_resolves_via_init_param_annotation(python_parser, fixture_bytes):
    """self.dep.* resolves via __init__ param type (DependencyType)."""
    file_bytes = fixture_bytes("ctor_param_self_call.py")
    symbols, imports, references = python_parser.parse(40, file_bytes)

    assert_symbols_invariants(symbols)
    assert_imports_invariants(imports)
    assert_symbol_references_invariants(references)

    call = next(
        r
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "self.dep.invoke"
    )
    assert call["ref_symbol_qualified_name"] == "DependencyType.invoke"

    access = next(
        r for r in references if r["ref_kind"] == "access" and r["ref_symbol_name"] == "self.dep"
    )
    assert access["ref_symbol_qualified_name"] == "DependencyType"


def test_symbol_references_access_and_type_annotation(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("references_cases.py")
    symbols, imports, references = python_parser.parse(4, file_bytes)

    assert len(symbols) == 6
    assert len(imports) == 1
    assert len(references) == 4
    assert_symbols_invariants(symbols)
    assert_imports_invariants(imports)
    assert_symbol_references_invariants(references)
    for r in references:
        assert_reference_shape(r, expected_file_id=4)

    assert any(
        r["ref_kind"] == "access" and r["ref_symbol_name"] == "self.value" for r in references
    )
    assert not any(
        r["ref_kind"] == "type_annotation" and r["ref_symbol_name"] == "int" for r in references
    )
    assert not any("Path" in r["ref_symbol_name"] for r in references)


def test_symbol_references_ids_are_unique_with_repeated_calls(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("duplicate_reference_ids.py")
    symbols, imports, references = python_parser.parse(5, file_bytes)

    assert len(symbols) == 2
    assert len(imports) == 0
    assert len(references) == 2
    assert_symbols_invariants(symbols)
    assert_imports_invariants(imports)
    assert_symbol_references_invariants(references)
    for r in references:
        assert_reference_shape(r, expected_file_id=5)

    call_refs = [
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "callee"
    ]
    assert len(call_refs) == 2
    assert {r["source_line"] for r in call_refs} == {6, 7}


def test_same_line_duplicate_calls_get_distinct_ids(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("same_line_duplicate_refs.py")
    symbols, imports, references = python_parser.parse(55, file_bytes)

    assert_symbols_invariants(symbols)
    assert_imports_invariants(imports)
    assert_symbol_references_invariants(references)
    for r in references:
        assert_reference_shape(r, expected_file_id=55)

    call_refs = [
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "callee"
    ]
    assert len(call_refs) == 2
    assert call_refs[0]["source_line"] == call_refs[1]["source_line"] == 6
    assert call_refs[0]["source_column"] != call_refs[1]["source_column"]
    assert call_refs[0]["id"] != call_refs[1]["id"]


def test_same_module_simple_name_gets_module_prefix(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ref_qn_same_module.py")
    _, _, references = python_parser.parse(50, file_bytes, module_qn="pkg.mod")

    assert_symbol_references_invariants(references)
    call = next(
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "helper"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.helper"


def test_absolute_from_import_rewrites_ref_qn(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ref_qn_absolute_import.py")
    _, _, references = python_parser.parse(51, file_bytes, module_qn="app.main")

    assert_symbol_references_invariants(references)
    call = next(
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "Thing.run"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.Thing.run"


def test_import_module_alias_rewrites_ref_qn(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ref_qn_import_alias.py")
    _, _, references = python_parser.parse(52, file_bytes, module_qn="app.main")

    assert_symbol_references_invariants(references)
    call = next(
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "m.Thing"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.Thing"


def test_relative_from_import_rewrites_ref_qn(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ref_qn_relative_import.py")
    _, _, references = python_parser.parse(53, file_bytes, module_qn="pkg.sub.caller")

    assert_symbol_references_invariants(references)
    call = next(r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "Foo")
    assert call["ref_symbol_qualified_name"] == "pkg.sub.sib.Foo"


def test_ctor_param_imported_type_rewrites_via_import_qn(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ctor_param_imported_type.py")
    _, _, references = python_parser.parse(54, file_bytes, module_qn="pkg.host")

    assert_symbol_references_invariants(references)
    call = next(
        r
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "self.dep.invoke"
    )
    assert call["ref_symbol_qualified_name"] == "other.types.DependencyType.invoke"

    access = next(
        r for r in references if r["ref_kind"] == "access" and r["ref_symbol_name"] == "self.dep"
    )
    assert access["ref_symbol_qualified_name"] == "other.types.DependencyType"


def test_param_receiver_call_resolves_via_annotation(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("param_receiver_call.py")
    _, _, references = python_parser.parse(56, file_bytes, module_qn="pkg.mod")

    assert_symbol_references_invariants(references)
    calls = [
        r
        for r in references
        if r["ref_kind"] == "call"
        and r["ref_symbol_name"] == "deployability_index.is_representative"
    ]
    assert len(calls) == 3
    assert all(
        r["ref_symbol_qualified_name"] == "pkg.mod.DeployabilityIndex.is_representative"
        for r in calls
    )


def test_source_symbol_id_is_the_enclosing_container(python_parser):
    source = (
        b"def helper():\n"
        b"    return 1\n"
        b"\n"
        b"def outer():\n"
        b"    def inner():\n"
        b"        return helper()\n"
        b"    return helper()\n"
        b"\n"
        b"helper()\n"
        b"\n"
        b"class Box:\n"
        b"    def run(self) -> helper:\n"
        b"        return helper()\n"
    )
    symbols, _, references = python_parser.parse(1, source, module_qn="pkg.mod")
    by_qn = index_symbols(symbols)
    calls = {
        r["source_line"]: r["source_symbol_id"]
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "helper"
    }
    assert calls[6] == by_qn["pkg.mod.outer.inner"]["id"]
    assert calls[7] == by_qn["pkg.mod.outer"]["id"]
    assert calls[9] is None
    assert calls[13] == by_qn["pkg.mod.Box.run"]["id"]

    annotation = next(
        r
        for r in references
        if r["ref_kind"] == "type_annotation" and r["ref_symbol_name"] == "helper"
    )
    assert annotation["source_symbol_id"] == by_qn["pkg.mod.Box.run"]["id"]
