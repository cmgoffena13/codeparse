import sys
from pathlib import Path

import pytest

from scripts.query import main
from src.db import CodeDB


def test_query_missing_index_requires_reload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["query.py", "--root", str(tmp_path), "sql", "SELECT 1"],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    message = str(exc.value)
    assert "No index" in message
    assert f"codeparse reload --cwd {tmp_path.resolve()}" in message
    assert "--reindex" not in message


def test_query_sql_reads_existing_index(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db = CodeDB(tmp_path)
    db.close()
    monkeypatch.setattr(
        sys,
        "argv",
        ["query.py", "--root", str(tmp_path), "sql", "SELECT count(*) FROM symbols"],
    )
    assert main() == 0
    out = capsys.readouterr().out
    assert "count(*)" in out
    assert "0" in out


def test_query_rejects_reindex_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["query.py", "--reindex", "--root", str(tmp_path), "sql", "SELECT 1"],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "--reindex" in capsys.readouterr().err
