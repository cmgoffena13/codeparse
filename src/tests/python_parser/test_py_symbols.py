from src.tests.python_parser._assertions import (
    assert_imports_invariants,
    assert_symbol_references_invariants,
    assert_symbols_invariants,
    index_symbols,
    symbol_key,
)


def test_python_fixture_file_parses_symbols_imports_and_references(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("file.py")
    symbols, imports, references = python_parser.parse(1, file_bytes)

    assert len(symbols) == 12
    assert len(imports) == 3
    assert len(references) == 4
    assert_symbols_invariants(symbols)
    assert_imports_invariants(imports)
    assert_symbol_references_invariants(references)

    qn = {symbol_key(s) for s in symbols}

    # Class + method nesting
    assert "FakeClass" in qn
    assert "FakeClass.__init__" in qn
    assert "FakeClass.fake_method" in qn
    assert "FakeClass.fake_property" in qn

    # Function + nested function
    assert "_noop_deco" in qn
    assert "fake_function" in qn
    assert "fake_function.nested_fake_function" in qn

    # Variable symbols exist
    assert "fake_path" in qn
    assert "alias_variable_in_another_file" in qn
    by_qn = index_symbols(symbols)
    assert by_qn["fake_path"]["kind"] == "variable"
    assert by_qn["alias_variable_in_another_file"]["kind"] == "variable"
    assert by_qn["FakeClass.fake_data"]["name"] == "self.fake_data"
    assert by_qn["FakeClass.fake_data"]["qualified_name"] == "FakeClass.fake_data"

    # Signatures are normalized to one line
    fake_fn = index_symbols(symbols)["fake_function"]
    assert "\n" not in fake_fn["signature"]
    multiline = index_symbols(symbols)["multiline_signature"]
    assert "\n" not in multiline["signature"]
    assert multiline["signature"].startswith("def multiline_signature(")
    assert multiline["signature"].endswith(") -> int:")

    # Docstrings extracted
    fake_class = index_symbols(symbols)["FakeClass"]
    assert fake_class["docstring"]
    assert "Fake Class Milti Line Docstring" in fake_class["docstring"]
    assert "This is a fake class with a multi line docstring." in fake_class["docstring"]
    assert fake_fn["docstring"]
    assert "Fake Function Docstring" in fake_fn["docstring"]

    # Decorators: line_start / signature include the decorated span; modifiers list kept.
    fake_prop = index_symbols(symbols)["FakeClass.fake_property"]
    assert fake_prop["line_start"] == 40  # first @_noop_deco line in file.py fixture
    assert "@_noop_deco" in fake_prop["signature"]
    assert "@property" in fake_prop["signature"]
    assert "def fake_property" in fake_prop["signature"]
    assert fake_prop["modifiers"] is not None
    assert "_noop_deco" in fake_prop["modifiers"]
    assert "property" in fake_prop["modifiers"]
    assert fake_prop["kind"] == "property"


def test_python_module_qn_prefixes_root_symbols(python_parser, fixture_bytes):
    """When module_qn is set, root symbols are prefixed; nested keep parent chain."""
    file_bytes = fixture_bytes("file.py")
    symbols, _imports, _references = python_parser.parse(1, file_bytes, module_qn="pkg.mod")

    assert_symbols_invariants(symbols)
    qn = {symbol_key(s) for s in symbols}

    assert "pkg.mod.FakeClass" in qn
    assert "pkg.mod.FakeClass.__init__" in qn
    assert "pkg.mod.FakeClass.fake_method" in qn
    assert "pkg.mod.FakeClass.fake_property" in qn
    assert "pkg.mod.FakeClass.fake_data" in qn
    assert "pkg.mod._noop_deco" in qn
    assert "pkg.mod.fake_function" in qn
    assert "pkg.mod.fake_function.nested_fake_function" in qn
    assert "pkg.mod.fake_path" in qn
    assert "pkg.mod.alias_variable_in_another_file" in qn
    assert "pkg.mod.multiline_signature" in qn

    # Unprefixed names must not appear when module_qn is set.
    assert "FakeClass" not in qn
    assert "fake_function" not in qn

    by_qn = index_symbols(symbols)
    assert by_qn["pkg.mod.FakeClass.fake_data"]["name"] == "self.fake_data"
    assert by_qn["pkg.mod.FakeClass"]["name"] == "FakeClass"


def test_python_fixture_another_file_has_fakeclass_call_reference(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("another_file.py")
    symbols, imports, references = python_parser.parse(2, file_bytes)

    assert len(symbols) == 4
    assert len(imports) == 1
    assert len(references) == 2
    assert_symbols_invariants(symbols)
    assert_imports_invariants(imports)
    assert_symbol_references_invariants(references)

    by_qn = index_symbols(symbols)

    # Should contain a call reference to FakeClass()
    assert any(r["ref_kind"] == "call" and "FakeClass" in r["ref_symbol_name"] for r in references)

    # Base classes extracted as resolved qualified names
    assert "AnotherClass" in by_qn
    assert by_qn["AnotherClass"]["base_qualified_names"] == [
        "src.tests.files_to_parse.python.file.FakeClass"
    ]
