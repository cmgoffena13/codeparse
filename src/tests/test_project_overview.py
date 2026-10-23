"""Tests for get_project_overview."""

from pathlib import Path

import pytest

from src.codeparse_mcp.project_overview import get_project_overview
from src.db import CodeDB
from src.processor import CodeProcessor


@pytest.fixture
def indexed_project(tmp_path: Path) -> Path:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "root_mod.py").write_text("def root_fn() -> None:\n    pass\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "demo"\n'
        'version = "0.0.1"\n'
        "\n"
        "[project.scripts]\n"
        'demo = "pkg.cli:main"\n'
        'missing = "not.a.module:run"\n',
        encoding="utf-8",
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "cli.py").write_text(
        "def main() -> None:\n    pass\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    (pkg / "app.py").write_text("app = object()\n", encoding="utf-8")
    (pkg / "main.py").write_text(
        'def run() -> None:\n    pass\n\nif __name__ == "__main__":\n    run()\n',
        encoding="utf-8",
    )
    (pkg / "worker.py").write_text("def work() -> None:\n    pass\n", encoding="utf-8")
    (pkg / "heavy.py").write_text(
        "def a() -> None:\n    pass\n\n"
        "def b() -> None:\n    pass\n\n"
        "def c() -> None:\n    pass\n\n"
        "def d() -> None:\n    pass\n",
        encoding="utf-8",
    )
    other = tmp_path / "other"
    other.mkdir()
    (other / "small.py").write_text("def one() -> None:\n    pass\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "main.py").write_text(
        "if __name__ == '__main__':\n    pass\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    db.close()
    return tmp_path


def test_project_overview_directories_and_entry_points(indexed_project: Path) -> None:
    db = CodeDB(indexed_project)
    try:
        out = get_project_overview(db)
        stored = [
            row["path"]
            for row in db.connection.execute(
                """
                SELECT f.path
                FROM entry_points AS e
                JOIN files AS f ON f.id = e.id
                ORDER BY f.path
                """
            )
        ]
    finally:
        db.close()

    assert stored == ["pkg/app.py", "pkg/cli.py", "pkg/main.py"]
    assert out.startswith("Directories - Top 10\n")
    assert "Legend:" not in out
    assert "  • pkg (29L, 8S, 6F)" in out
    assert any(line.startswith("  • root (") for line in out.splitlines())
    assert not any(line.startswith("  • None ") for line in out.splitlines())
    assert out.index("  • pkg (") < out.index("  • other (")

    script_at = out.index("  • pkg/cli.py")
    app_at = out.index("  • pkg/app.py")
    main_at = out.index("  • pkg/main.py")
    assert "pkg.cli.main" not in out
    assert "not.a.module" not in out
    assert script_at < app_at < main_at
    assert out.count("pkg/main.py") == 1
    assert out.count("pkg/cli.py") == 1
    assert any(
        line.startswith("  • pkg/cli.py (") and "L" in line and line.rstrip().endswith("S)")
        for line in out.splitlines()
    )
    assert "tests/main.py" not in out
    assert "pkg/worker.py" not in out


def test_project_overview_reads_pyproject_only(
    indexed_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.read_text

    def _read_text(self: Path, *args, **kwargs):
        if self.name != "pyproject.toml":
            raise AssertionError(f"overview read {self}")
        return original(self, *args, **kwargs)

    db = CodeDB(indexed_project)
    monkeypatch.setattr(Path, "read_text", _read_text)
    try:
        out = get_project_overview(db)
    finally:
        db.close()
    assert "pkg/cli.py" in out


def test_main_guard_tracks_content_and_deletion(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    script = tmp_path / "run.py"
    script.write_text(
        "def run() -> None:\n    pass\n\nif __name__ == '__main__':\n    run()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    try:
        CodeProcessor(db, tmp_path).process()
        assert "run.py" in get_project_overview(db)
        assert (
            db.connection.execute("SELECT has_main_guard FROM entry_points").fetchone()[
                "has_main_guard"
            ]
            == 1
        )

        script.write_text("def run() -> None:\n    pass\n", encoding="utf-8")
        CodeProcessor(db, tmp_path).process()
        assert "run.py" not in get_project_overview(db)
        assert db.connection.execute("SELECT COUNT(*) AS c FROM entry_points").fetchone()["c"] == 0

        script.unlink()
        CodeProcessor(db, tmp_path).process()
        assert db.connection.execute("SELECT COUNT(*) AS c FROM entry_points").fetchone()["c"] == 0
    finally:
        db.close()
