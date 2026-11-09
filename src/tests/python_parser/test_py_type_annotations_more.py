from src.tests.python_parser._assertions import assert_symbol_references_invariants


def test_type_annotations_optional_generics_and_forward_refs(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("type_annotations_complex.py")
    symbols, references = python_parser.parse(13, file_bytes)

    assert len(symbols) == 1
    assert len(references) == 1
    assert_symbol_references_invariants(references)

    assert not any(
        r["ref_kind"] == "type_annotation" and r["ref_symbol_name"] == "list" for r in references
    )
    # Optional/List/typing.Path skipped as stdlib-mapped; quoted forward ref remains
    assert any(
        r["ref_kind"] == "type_annotation" and r["ref_symbol_name"] == '"Path"' for r in references
    )


def test_return_type_annotation_is_indexed(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("return_type_annotation.py")
    symbols, references = python_parser.parse(14, file_bytes, module_qn="pkg.mod")

    assert any(s["qualified_name"] == "pkg.mod.Worker" for s in symbols)
    assert_symbol_references_invariants(references)
    assert any(
        r["ref_kind"] == "type_annotation"
        and r["ref_symbol_name"] == "Worker"
        and r["ref_symbol_qualified_name"] == "pkg.mod.Worker"
        for r in references
    )
