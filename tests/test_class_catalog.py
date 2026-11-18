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
            "start_line": 1,
            "end_line": 4,
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
            "start_line": 2,
            "end_line": 3,
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
            "start_line": 6,
            "end_line": 7,
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
    assert catalog.members_by_parent_id[1]["run"]["qualified_name"] == "pkg.Box.run"
    catalog.drop_file(10)
    assert catalog.by_qualified_name == {}
    assert catalog.members_by_parent_id == {}
    assert catalog.classes_by_name == {}


def test_canonical_class_qn_uses_leaf_index_for_unique_package_match() -> None:
    catalog = ClassCatalog()
    catalog.put(
        {
            "id": 1,
            "file_id": 1,
            "parent_id": None,
            "parent": None,
            "name": "Engine",
            "qualified_name": "sqlmesh.core.engine.Engine",
            "kind": "class",
            "start_line": 1,
            "end_line": 2,
            "signature": "class Engine:",
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
            "file_id": 2,
            "parent_id": None,
            "parent": None,
            "name": "Engine",
            "qualified_name": "other.adapters.Engine",
            "kind": "class",
            "start_line": 1,
            "end_line": 2,
            "signature": "class Engine:",
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
            "file_id": 3,
            "parent_id": None,
            "parent": None,
            "name": "Engine",
            "qualified_name": "sqlmesh.core.alt.Engine",
            "kind": "class",
            "start_line": 1,
            "end_line": 2,
            "signature": "class Engine:",
            "docstring": None,
            "modifiers": None,
            "language": "python",
            "is_test": False,
            "base_qualified_names": [],
        }
    )
    assert catalog.canonical_class_qn("sqlmesh.core.engine.Engine") == "sqlmesh.core.engine.Engine"
    assert catalog.canonical_class_qn("other.Engine") == "other.adapters.Engine"
    assert catalog.canonical_class_qn("sqlmesh.core.Engine") is None
    catalog.drop("sqlmesh.core.engine.Engine")
    assert "sqlmesh.core.engine.Engine" not in catalog.classes_by_name.get("Engine", {})
    assert catalog.canonical_class_qn("sqlmesh.core.engine.Engine") is None
