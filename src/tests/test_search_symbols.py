"""Tests for search_symbols MCP query."""

import shutil
from pathlib import Path

from src.codeparse_mcp.search_symbols import build_fts_query, search_symbols
from src.db import CodeDB
from src.processor import CodeProcessor


def _index(tmp_path: Path, python_fixtures_dir: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(python_fixtures_dir / "search_symbols", root)
    db = CodeDB(root)
    CodeProcessor(db, root).process()
    db.close()
    return root


def _clause(word: str) -> str:
    return (
        f"name: {word} OR parent: {word} OR signature: {word}* "
        f"OR docstring: {word}* OR modifiers: {word}*"
    )


def test_build_fts_query_ors_each_word() -> None:
    assert build_fts_query("plan") == _clause("plan")
    assert build_fts_query("def plan") == f"{_clause('def')} OR {_clause('plan')}"
    assert build_fts_query("class Plan") == f"{_clause('class')} OR {_clause('Plan')}"
    assert build_fts_query("async def load") == (
        f"{_clause('async')} OR {_clause('def')} OR {_clause('load')}"
    )
    assert build_fts_query("Context.plan") == "parent: Context AND name: plan"
    assert build_fts_query("   ") == ""


def test_search_symbols_excludes_is_test_by_default(
    tmp_path: Path, python_fixtures_dir: Path
) -> None:
    root = _index(tmp_path, python_fixtures_dir)
    db = CodeDB(root)
    try:
        out = search_symbols(db, "format_model", limit=20, include_tests=False)
        assert "pkg.prod.format_model" in out
        assert "test_format_model" not in out
        assert "tests/" not in out
        assert "Legend:" not in out
        assert "Search results" not in out
        assert "pkg/prod.py" in out
        assert any(
            line.startswith("  #") and " • " in line and "pkg.prod.format_model" in line
            for line in out.splitlines()
        )
        assert "Sig:" not in out
        assert "Doc:" not in out
    finally:
        db.close()


def test_search_symbols_matches_decorator_modifiers(
    tmp_path: Path, python_fixtures_dir: Path
) -> None:
    root = _index(tmp_path, python_fixtures_dir)
    db = CodeDB(root)
    try:
        rows = db.connection.execute(
            """
            SELECT s.qualified_name
            FROM symbols_fts
            INNER JOIN symbols AS s ON s.id = symbols_fts.rowid
            WHERE symbols_fts MATCH 'modifiers : traced*'
            """
        ).fetchall()
        assert [row["qualified_name"] for row in rows] == ["pkg.prod.load_rows"]
    finally:
        db.close()


def test_search_symbols_include_tests(tmp_path: Path, python_fixtures_dir: Path) -> None:
    root = _index(tmp_path, python_fixtures_dir)
    db = CodeDB(root)
    try:
        out = search_symbols(db, "format_model", limit=20, include_tests=True)
        assert "pkg.prod.format_model" in out
        assert "test_format_model" in out
    finally:
        db.close()


def _rank(out: str, qualified_name: str) -> int:
    line = next(item for item in out.splitlines() if item.endswith(qualified_name))
    return int(line.split()[0].removeprefix("#"))


def test_search_dotted_field_requires_parent_and_name(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("#\n", encoding="utf-8")
    for package in ("pkg", "pkg/plan", "pkg/cli"):
        path = root.joinpath(*package.split("/"))
        path.mkdir(parents=True)
        (path / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg/plan/model.py").write_text(
        "class Plan:\n    plan_id: str\n",
        encoding="utf-8",
    )
    (root / "pkg/cli/main.py").write_text(
        "def plan() -> None:\n    return None\n",
        encoding="utf-8",
    )
    db = CodeDB(root)
    CodeProcessor(db, root).process()
    db.close()
    db = CodeDB(root)
    try:
        out = search_symbols(db, "Plan.plan_id", limit=10, include_tests=False)
        names = [line.split("•", 1)[1].strip() for line in out.splitlines() if "•" in line]
        assert names == ["pkg.plan.model.Plan.plan_id"]
    finally:
        db.close()


def test_search_symbols_dot_is_parent_and_name(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("#\n", encoding="utf-8")
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(
        "class Context:\n"
        "    def plan(self) -> None:\n"
        "        return None\n"
        "\n"
        "class Other:\n"
        "    def plan(self) -> None:\n"
        "        return None\n"
        "\n"
        "def plan() -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )
    db = CodeDB(root)
    CodeProcessor(db, root).process()
    db.close()
    db = CodeDB(root)
    try:
        out = search_symbols(db, "Context.plan", limit=10, include_tests=False)
        names = [line.split("•", 1)[1].strip() for line in out.splitlines() if "•" in line]
        assert names == ["pkg.mod.Context.plan"]
    finally:
        db.close()


def test_search_name_outranks_a_long_docstring(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("#\n", encoding="utf-8")
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(
        "def plan() -> None:\n"
        "    return None\n"
        "\n"
        "def other() -> None:\n"
        '    """' + ("plan " * 80) + '"""\n'
        "    return None\n",
        encoding="utf-8",
    )
    db = CodeDB(root)
    CodeProcessor(db, root).process()
    db.close()
    db = CodeDB(root)
    try:
        out = search_symbols(db, "def plan", limit=10, include_tests=False)
        assert _rank(out, "pkg.mod.plan") < _rank(out, "pkg.mod.other")
    finally:
        db.close()


def test_search_symbols_ranks_multi_word_matches_first(
    tmp_path: Path, python_fixtures_dir: Path
) -> None:
    root = _index(tmp_path, python_fixtures_dir)
    db = CodeDB(root)
    try:
        out = search_symbols(db, "render dialect", limit=20, include_tests=False)
        names = [line.split("•", 1)[1].strip() for line in out.splitlines() if "•" in line]
        assert names[0] == "pkg.prod.render_query"
        assert "pkg.prod.render_tree" in names
        assert "pkg.prod.dialect_name" in names
    finally:
        db.close()


def test_search_symbols_groups_by_file_with_rank(tmp_path: Path, python_fixtures_dir: Path) -> None:
    root = _index(tmp_path, python_fixtures_dir)
    db = CodeDB(root)
    try:
        out = search_symbols(db, "format_model", limit=20, include_tests=False)
        hits = [line for line in out.splitlines() if line.startswith("  #")]
        assert hits
        ranks: list[int] = []
        for line in hits:
            # "  #3 • qualified_name" with the rank padded to the widest rank
            parts = line.split()
            assert parts[0].startswith("#")
            assert parts[1] == "•"
            ranks.append(int(parts[0].removeprefix("#")))
        assert sorted(ranks) == list(range(1, len(ranks) + 1))
        name_at = [line.index(line.split()[-1]) for line in hits]
        assert len(set(name_at)) == 1
    finally:
        db.close()
