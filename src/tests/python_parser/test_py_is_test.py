from src.tests.python_parser._assertions import (
    assert_imports_invariants,
    assert_symbols_invariants,
    index_symbols,
)


def test_is_test_detection_pytest_and_unittest(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("is_test_cases.py")
    symbols, imports, references = python_parser.parse(3, file_bytes)

    assert len(symbols) == 5
    assert len(imports) == 1
    assert len(references) == 0
    assert_symbols_invariants(symbols)
    assert_imports_invariants(imports)

    by_qn = index_symbols(symbols)

    assert by_qn["test_top"]["is_test"] is True
    assert by_qn["TestPy"]["is_test"] is True
    assert by_qn["TestPy.test_m"]["is_test"] is True
    assert by_qn["TestUT"]["is_test"] is True
    assert by_qn["TestUT.test_u"]["is_test"] is True
