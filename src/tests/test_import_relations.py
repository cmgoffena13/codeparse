"""Tests for get_import_relations."""

from pathlib import Path

from src.codeparse_mcp import import_relations as import_relations_mod
from src.codeparse_mcp.import_relations import _format_rows, get_import_relations
from src.db import CodeDB
from src.processor import CodeProcessor
from src.tests.fixtures.import_relations import (
    index_directory_package,
    index_external_user,
    index_internal_package,
    index_stdlib_user,
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
        assert "• pkg/user.py" in out
        assert "  └─ pkg.user.run" in out or "  ├─ pkg.user.run" in out
        assert "• pkg.target.helper (C)" in out
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
        assert "├─" not in deps
        assert "└─" not in deps
    finally:
        db.close()


def test_import_relations_internal_file_dependencies(tmp_path: Path) -> None:
    index_internal_package(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "pkg.user", relation="dependencies", include_tests=False)
        assert "• pkg/user.py" not in out
        assert "pkg.user.run" in out
        assert "  • pkg.target.helper (C)" in out
        assert "  • pkg.target.FLAG (A)" in out
        assert "├─ pkg.user.run" not in out
        assert "\n\npkg.user.run\n" in out or out.startswith("pkg.user.run\n")
    finally:
        db.close()


def test_import_relations_internal_dependencies_omit_same_file_targets(
    tmp_path: Path,
) -> None:
    write_gitignore(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "solo.py").write_text(
        "def helper() -> int:\n    return 1\n\n\ndef run() -> int:\n    return helper()\n",
        encoding="utf-8",
    )
    (pkg / "other.py").write_text(
        "from pkg.solo import helper\n\n\ndef go() -> int:\n    return helper()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)
    try:
        solo = get_import_relations(db, "pkg.solo", relation="dependencies", include_tests=False)
        assert solo == "No import relations found."
        other = get_import_relations(db, "pkg.other", relation="dependencies", include_tests=False)
        assert "• pkg/other.py" not in other
        assert "• pkg.solo.helper (C)" in other
    finally:
        db.close()


def test_import_relations_internal_dependencies_omit_external_and_unresolved(
    tmp_path: Path,
) -> None:
    write_gitignore(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text(
        "def helper() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (pkg / "user.py").write_text(
        "from pkg.target import helper\n"
        "from sqlglot import Exp\n\n"
        "def run(node) -> int:\n"
        "    node.this\n"
        "    Exp()\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)
    try:
        out = get_import_relations(db, "pkg.user", relation="dependencies", include_tests=False)
        assert "• pkg.target.helper (C)" in out
        assert "sqlglot.Exp" not in out
        assert "node.this" not in out
    finally:
        db.close()


def test_import_relations_directory_dependents(tmp_path: Path) -> None:
    index_directory_package(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "pkg.lib", include_tests=False)
        assert "• pkg/caller.py" in out
        assert "  └─ pkg.caller.go" in out or "  ├─ pkg.caller.go" in out
        assert "• pkg.lib.b.beta (C)" in out
    finally:
        db.close()


def test_import_relations_directory_dependencies(tmp_path: Path) -> None:
    index_directory_package(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "pkg.lib", relation="dependencies", include_tests=False)
        assert "• pkg/lib/b.py" in out
        assert "pkg.lib.b.beta" in out
        assert "  • pkg.lib.a.alpha (C)" in out
        assert "├─" not in out
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
        assert "• app.py" in out
        assert "  └─ app.run" in out or "  ├─ app.run" in out
        assert "• sqlglot.Exp (C)" in out
        assert out.index("• app.py") < out.index("• sqlglot.Exp (C)")
    finally:
        db.close()


def test_import_relations_stdlib_dependents_via_symbol_use(tmp_path: Path) -> None:
    index_stdlib_user(tmp_path)
    db = CodeDB(tmp_path)
    try:
        out = get_import_relations(db, "re", include_tests=False)
        assert "• app.py" in out
        assert "• re.compile (C)" in out
        assert "• re.search (C)" in out
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
        assert "• pkg/user.py" in out
        assert "  └─ (module)" in out
        assert "• pkg.target.helper (C) (3)" in out
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
        assert "• pkg/user.py" in out
        assert "  └─ pkg.user.Box.run" in out
        assert "• pkg.target.helper (C)" in out
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
        assert "• pkg/user.py" in out
        assert "  └─ pkg.user.outer" in out
        assert "     └─ pkg.user.outer.inner" in out
        assert "• pkg.target.helper (C)" in out
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


def test_import_relations_orders_sources_by_line_with_module_first(tmp_path: Path) -> None:
    write_gitignore(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text(
        "def helper() -> int:\n    return 1\n\ndef other() -> int:\n    return 2\n",
        encoding="utf-8",
    )
    (pkg / "user.py").write_text(
        "from pkg.target import helper, other\n\n"
        "def early() -> int:\n"
        "    return helper()\n\n"
        "def late() -> int:\n"
        "    return other()\n\n"
        "helper()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    try:
        out = get_import_relations(db, "pkg.target", include_tests=False)
        module_at = out.index("  ├─ (module)")
        early_at = out.index("  ├─ pkg.user.early")
        late_at = out.index("  └─ pkg.user.late")
        assert module_at < early_at < late_at
    finally:
        db.close()


def test_format_rows_page_includes_total_count(monkeypatch) -> None:
    monkeypatch.setattr(import_relations_mod, "_MAX_ROWS", 2)
    rows = [
        {
            "source_path": f"a{index}.py",
            "source_qualified_name": f"a{index}.run",
            "target_qualified_name": "pkg.t.f",
            "ref_kind": "call",
        }
        for index in range(5)
    ]
    page_one = _format_rows(rows, relation="dependents", page=1)
    page_two = _format_rows(rows, relation="dependents", page=2)
    page_three = _format_rows(rows, relation="dependents", page=3)
    deps = _format_rows(rows, relation="dependencies", page=1)
    assert "a0.run" in page_one
    assert "a2.run" not in page_one
    assert "a2.run" in page_two
    assert "a4.run" in page_three
    assert "… page 1 of 3 (2 of 5 dependents)" in page_one
    assert "… page 2 of 3 (2 of 5 dependents)" in page_two
    assert "… page 3 of 3 (1 of 5 dependents)" in page_three
    assert "… page 1 of 3 (2 of 5 dependencies)" in deps
    assert _format_rows(rows, relation="dependents", page=4) == (
        "No more dependents; page 4 is past 3."
    )
    assert _format_rows(rows, relation="dependents", page=0) == ("Invalid page; pass page >= 1.")
