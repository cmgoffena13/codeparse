def symbol_key(symbol: dict) -> str:
    return symbol["qualified_name"]


def index_symbols(symbols: list[dict]) -> dict:
    return {symbol_key(symbol): symbol for symbol in symbols}


def assert_reference_shape(ref: dict, expected_file_id: int) -> None:
    assert ref["ref_kind"] in {"call", "access", "type_annotation", "type"}
    assert isinstance(ref["ref_symbol_name"], str)
    assert ref["ref_symbol_name"]
    assert isinstance(ref["ref_symbol_qualified_name"], str)
    assert ref["ref_symbol_qualified_name"]
    assert ref["source_file_id"] == expected_file_id
    assert isinstance(ref["source_line"], int)
    assert ref["source_line"] >= 1
    assert isinstance(ref["source_column"], int)
    assert ref["source_column"] >= 0
    assert isinstance(ref["context"], str)
    assert ref["context"]
    assert ref["source_symbol_id"] is None or isinstance(ref["source_symbol_id"], int)


def assert_symbol_references_invariants(references: list[dict]) -> None:
    ids = [r["id"] for r in references]
    assert len(ids) == len(set(ids)), "symbol_references ids must be unique"
    keys = {
        (
            r["ref_symbol_qualified_name"],
            r["ref_kind"],
            r["source_line"],
            r["source_column"],
        )
        for r in references
    }
    assert len(keys) == len(references), (
        "symbol_references must be unique per "
        "(ref_symbol_qualified_name, ref_kind, source_line, source_column)"
    )


def assert_symbols_invariants(symbols: list[dict]) -> None:
    ids = [s["id"] for s in symbols]
    assert len(ids) == len(set(ids)), "symbols ids must be unique"
    names = [s["qualified_name"] for s in symbols]
    assert len(names) == len(set(names)), "symbols qualified_name must be unique per file"


def assert_imports_invariants(imports: list[dict]) -> None:
    ids = [i["id"] for i in imports]
    assert len(ids) == len(set(ids)), "imports ids must be unique"
    keys = {(i["import_path"], i["imported_symbol"]) for i in imports}
    assert len(keys) == len(imports), "imports must be unique per (import_path, imported_symbol)"
