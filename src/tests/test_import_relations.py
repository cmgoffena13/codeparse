"""Tests for get_import_relations."""

from pathlib import Path

from src.codeparse_mcp.import_relations import get_import_relations
from src.db import CodeDB
from src.processor import CodeProcessor
from src.tests.fixtures.import_relations import (
    index_directory_package,
    index_external_user,
    index_internal_package,
    write_gitignore,
)


def test_import_relations_rejects_blank_target(tmp_path: Path) -> None:
    index_internal_package(tmp_path)
    db = CodeDB(tmp_path)
    try:
        assert get_import_relations(db, "  ", include_tests=False) == (
            "No target given; pass a non-empty dotted module path."
        )
    finally:
        db.close()


def test_import_relations_internal_file_dependents(tmp_path: Path) -> None:
    index_internal_package(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "pkg.target", include_tests=False)
        assert "pkg.target.helper (C) (" in out
        assert "• pkg/user.py" in out
        assert "  └─ pkg.user.run" in out or "  ├─ pkg.user.run" in out
        assert "tests/test_user.py" not in out
        assert "pkg.mod_extra" not in out
    finally:
        db.close()


def test_import_relations_include_tests_only_dependents(tmp_path: Path) -> None:
    index_internal_package(tmp_path)
    db = CodeDB(tmp_path)
    try:
        hidden = get_import_relations(db, "pkg.target", include_tests=False)
        assert "tests/test_user.py" not in hidden
        shown = get_import_relations(db, "pkg.target", include_tests=True)
        assert "tests/test_user.py" in shown
        assert "pkg.target.helper" in shown
        deps = get_import_relations(db, "tests", relation="dependencies", include_tests=False)
        assert "pkg.target.helper" in deps
        assert "tests/test_user.py" in deps
    finally:
        db.close()


def test_import_relations_internal_file_dependencies(tmp_path: Path) -> None:
    index_internal_package(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "pkg.user", relation="dependencies", include_tests=False)
        assert "pkg.target.helper (C) (" in out
        assert "• pkg/user.py" in out
        assert "  └─ pkg.user.run" in out or "  ├─ pkg.user.run" in out
        assert "pkg.target.FLAG (A) (" in out
    finally:
        db.close()


def test_import_relations_directory_dependents(tmp_path: Path) -> None:
    index_directory_package(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "pkg.lib", include_tests=False)
        assert "pkg.lib.b.beta (C) (" in out
        assert "• pkg/caller.py" in out
        assert "  └─ pkg.caller.go" in out or "  ├─ pkg.caller.go" in out
    finally:
        db.close()


def test_import_relations_directory_dependencies(tmp_path: Path) -> None:
    index_directory_package(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "pkg.lib", relation="dependencies", include_tests=False)
        assert "pkg.lib.a.alpha (C) (" in out
        assert "• pkg/lib/b.py" in out
        assert "  └─ pkg.lib.b.beta" in out or "  ├─ pkg.lib.b.beta" in out
    finally:
        db.close()


def test_import_relations_prefix_safety(tmp_path: Path) -> None:
    index_internal_package(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "pkg.mod", include_tests=False)
        assert "mod_extra" not in out
        assert out == "No import relations found."
    finally:
        db.close()


def test_import_relations_external_dependents(tmp_path: Path) -> None:
    index_external_user(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "sqlglot", include_tests=False)
        assert "sqlglot.Exp (C) (" in out
        assert "• app.py" in out
        assert "  └─ app.run" in out or "  ├─ app.run" in out
    finally:
        db.close()


def test_import_relations_module_level_aggregates_without_lines(tmp_path: Path) -> None:
    write_gitignore(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text(
        "def helper() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (pkg / "user.py").write_text(
        "from pkg.target import helper\n\nhelper()\nhelper()\nhelper()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    try:
        out = get_import_relations(db, "pkg.target", include_tests=False)
        assert "pkg.target.helper (C) (3)" in out
        assert "• pkg/user.py" in out
        assert "  └─ (module)" in out
        assert "L3" not in out
        assert "L4" not in out
        assert "L5" not in out
    finally:
        db.close()


def test_import_relations_groups_by_used_symbol(tmp_path: Path) -> None:
    write_gitignore(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text(
        "def helper() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (pkg / "user.py").write_text(
        "from pkg.target import helper\n\n\n"
        "class Box:\n"
        "    def run(self) -> int:\n"
        "        return helper()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    try:
        out = get_import_relations(db, "pkg.target", include_tests=False)
        assert "pkg.target.helper (C) (1)" in out
        assert "• pkg/user.py" in out
        assert "  └─ pkg.user.Box.run" in out
        assert "  └─ pkg.user.Box\n" not in out
    finally:
        db.close()


def test_import_relations_nests_only_real_source_symbols(tmp_path: Path) -> None:
    write_gitignore(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text(
        "def helper() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (pkg / "user.py").write_text(
        "from pkg.target import helper\n\n\n"
        "def outer() -> int:\n"
        "    helper()\n"
        "    def inner() -> int:\n"
        "        return helper()\n"
        "    return inner()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    try:
        out = get_import_relations(db, "pkg.target", include_tests=False)
        assert "pkg.target.helper (C) (2)" in out
        assert "• pkg/user.py" in out
        assert "  └─ pkg.user.outer" in out
        assert "     └─ pkg.user.outer.inner" in out
    finally:
        db.close()


def test_import_relations_external_dependencies_unavailable(tmp_path: Path) -> None:
    index_external_user(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "sqlglot", relation="dependencies", include_tests=False)
        assert out == "External package dependencies are not available."
    finally:
        db.close()
