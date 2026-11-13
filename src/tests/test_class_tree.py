from pathlib import Path

import pytest

from src.codeparse_mcp.class_tree import get_class_tree
from src.db import CodeDB
from src.processor import CodeProcessor


@pytest.fixture
def indexed_hierarchy(tmp_path: Path) -> Path:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "base.py").write_text(
        "class Parent:\n    pass\n\nclass Sibling(Parent):\n    pass\n\nclass Alone:\n    pass\n",
        encoding="utf-8",
    )
    (pkg / "child.py").write_text(
        "from pkg.base import Parent\n"
        "\n"
        "class Child(Parent):\n"
        "    pass\n"
        "\n"
        "class Other(Child):\n"
        "    pass\n"
        "\n"
        "class Grand(Child):\n"
        "    pass\n",
        encoding="utf-8",
    )
    (pkg / "external_user.py").write_text(
        "from elsewhere import ExtBase\n"
        "\n"
        "class UserModel(ExtBase):\n"
        "    pass\n"
        "\n"
        "class AdminUserModel(UserModel):\n"
        "    pass\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_parent.py").write_text(
        "from pkg.base import Parent\n\nclass TestChild(Parent):\n    pass\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    db.close()
    return tmp_path


def test_class_tree_parent_chain_and_descendant_glyphs(indexed_hierarchy: Path) -> None:
    db = CodeDB(indexed_hierarchy)
    try:
        out = get_class_tree(db, "pkg.child.Child", include_tests=False)
        assert "pkg/" not in out
        assert out.startswith("pkg.base.Parent\n")
        assert "└── pkg.child.Child\n" in out
        assert "├── pkg.child.Grand\n" in out or "├── pkg.child.Other\n" in out
        assert "└── pkg.child.Grand\n" in out or "└── pkg.child.Other\n" in out
        assert "pkg.base.Sibling" not in out
        assert "TestChild" not in out
    finally:
        db.close()


def test_class_tree_include_tests(indexed_hierarchy: Path) -> None:
    db = CodeDB(indexed_hierarchy)
    try:
        out = get_class_tree(db, "pkg.base.Parent", include_tests=True)
        assert "tests.test_parent.TestChild" in out
    finally:
        db.close()


def test_class_tree_external_base(indexed_hierarchy: Path) -> None:
    db = CodeDB(indexed_hierarchy)
    try:
        out = get_class_tree(db, "pkg.external_user.UserModel", include_tests=False)
        assert out.startswith("elsewhere.ExtBase\n")
        assert "└── pkg.external_user.UserModel\n" in out
        assert "└── pkg.external_user.AdminUserModel\n" in out
    finally:
        db.close()


def test_class_tree_leaf_alone(indexed_hierarchy: Path) -> None:
    db = CodeDB(indexed_hierarchy)
    try:
        out = get_class_tree(db, "pkg.base.Alone", include_tests=False)
        assert out == "pkg.base.Alone\n"
    finally:
        db.close()


def test_class_tree_unknown_qn_is_single_node(indexed_hierarchy: Path) -> None:
    db = CodeDB(indexed_hierarchy)
    try:
        assert get_class_tree(db, "pkg.base.Missing", include_tests=False) == ("pkg.base.Missing\n")
        assert "non-empty qualified_name" in get_class_tree(db, "  ", include_tests=False)
    finally:
        db.close()
