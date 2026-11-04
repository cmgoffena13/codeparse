from src.parsers.class_catalog import ClassCatalog


def test_class_catalog_stores_class_and_method_skips_function_and_drop_file() -> None:
    catalog = ClassCatalog()
    catalog.put(
        {
            "id": 1,
            "file_id": 10,
            "parent_id": None,
            "parent": None,
            "name": "Box",
            "qualified_name": "pkg.Box",
            "kind": "class",
            "line_start": 1,
            "line_end": 4,
            "signature": "class Box:",
            "docstring": None,
            "modifiers": None,
            "language": "python",
            "is_test": False,
            "base_qualified_names": [],
        }
    )
    catalog.put(
        {
            "id": 2,
            "file_id": 10,
            "parent_id": 1,
            "parent": "Box",
            "name": "run",
            "qualified_name": "pkg.Box.run",
            "kind": "method",
            "line_start": 2,
            "line_end": 3,
            "signature": "def run(self):",
            "docstring": None,
            "modifiers": None,
            "language": "python",
            "is_test": False,
            "base_qualified_names": [],
        }
    )
    catalog.put(
        {
            "id": 3,
            "file_id": 10,
            "parent_id": None,
            "parent": None,
            "name": "helper",
            "qualified_name": "pkg.helper",
            "kind": "function",
            "line_start": 6,
            "line_end": 7,
            "signature": "def helper():",
            "docstring": None,
            "modifiers": None,
            "language": "python",
            "is_test": False,
            "base_qualified_names": [],
        }
    )
    assert "pkg.Box" in catalog.by_qualified_name
    assert "pkg.Box.run" in catalog.by_qualified_name
    assert "pkg.helper" not in catalog.by_qualified_name
    catalog.drop_file(10)
    assert catalog.by_qualified_name == {}
