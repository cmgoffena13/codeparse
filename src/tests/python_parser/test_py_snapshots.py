import pytest

from src.tests.python_parser._assertions import (
    assert_symbol_references_invariants,
    assert_symbols_invariants,
)


@pytest.mark.parametrize(
    ("fixture_name", "file_id", "expected_counts"),
    [
        ("file.py", 1, (12, 4)),
        ("another_file.py", 2, (4, 2)),
        ("is_test_cases.py", 3, (5, 0)),
        ("references_cases.py", 4, (6, 4)),
        ("duplicate_reference_ids.py", 5, (2, 2)),
    ],
)
def test_parse_twice_counts_unchanged(
    python_parser,
    fixture_bytes,
    fixture_name: str,
    file_id: int,
    expected_counts: tuple,
):
    file_bytes = fixture_bytes(fixture_name)
    first = python_parser.parse(file_id, file_bytes)
    second = python_parser.parse(file_id, file_bytes)

    assert tuple(len(x) for x in first) == expected_counts
    assert tuple(len(x) for x in second) == expected_counts

    for batch in (first, second):
        symbols, references = batch
        assert_symbols_invariants(symbols)
        if references:
            assert_symbol_references_invariants(references)
