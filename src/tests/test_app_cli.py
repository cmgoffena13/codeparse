import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.app import main
from src.cli import install_mcp as install_mcp_mod
from src.cli.install_mcp import (
    _load_config,
    claude_desktop_config_path,
    cursor_mcp_config_path,
    install_mcp,
    merge_mcp_server,
    resolve_cli_path,
)
from src.utils import get_version


def test_bare_codeparse_prints_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["codeparse"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "mcp" in out
    assert "index" in out


def test_version_flag_prints_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["codeparse", "--version"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "codeparse Version:" in out
    assert get_version() in out


def test_info_flag_prints_paths_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "codeparse-config"
    monkeypatch.setenv("CODE_PARSE_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(sys, "argv", ["codeparse", "--info"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "CLI Path:" in out
    assert "Config Directory:" in out
    assert str(config_dir) in out


def test_mcp_missing_directory_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    missing = tmp_path / "no-such-dir"
    monkeypatch.setattr(sys, "argv", ["codeparse", "mcp", "--cwd", str(missing)])
    assert main() == 1
    err = capsys.readouterr().err
    assert "Not a directory" in err


def test_mcp_missing_gitignore_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "argv", ["codeparse", "mcp", "--cwd", str(tmp_path)])
    assert main() == 1
    err = capsys.readouterr().err
    assert ".gitignore not found" in err
    assert "are you in a git repository?" in err
    assert str(tmp_path.resolve() / ".gitignore") in err


def test_main_starts_mcp_stdio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# fixture\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["codeparse", "mcp", "--cwd", str(tmp_path)])
    fake_mcp = MagicMock()
    fake_server = MagicMock()
    fake_server.mcp = fake_mcp
    monkeypatch.setitem(sys.modules, "src.codeparse_mcp.server", fake_server)
    assert main() == 0
    fake_mcp.run.assert_called_once_with(transport="stdio", show_banner=False)


def test_install_mcp_merges_into_cursor_and_claude(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    cursor = tmp_path / "cursor-config" / "mcp.json"
    claude = tmp_path / "claude-config" / "claude_desktop_config.json"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(
        json.dumps({"mcpServers": {"other": {"command": "noop"}}}),
        encoding="utf-8",
    )
    fake_cli = tmp_path / "codeparse"
    fake_cli.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["codeparse", "mcp", "install"])
    monkeypatch.setattr(
        "src.cli.install_mcp.cursor_mcp_config_path",
        lambda: cursor,
    )
    monkeypatch.setattr(
        "src.cli.install_mcp.claude_desktop_config_path",
        lambda: claude,
    )
    monkeypatch.setattr(
        "src.cli.install_mcp.resolve_cli_path",
        lambda: fake_cli,
    )

    assert main() == 0
    out = capsys.readouterr().out
    assert str(cursor) in out
    assert str(claude) in out
    assert '"codeparse"' in out
    assert "${workspaceFolder}" in out

    cursor_data = json.loads(cursor.read_text(encoding="utf-8"))
    assert cursor_data["mcpServers"]["other"]["command"] == "noop"
    assert cursor_data["mcpServers"]["codeparse"] == {
        "type": "stdio",
        "command": str(fake_cli.resolve()),
        "args": ["mcp", "--cwd", "${workspaceFolder}"],
    }

    claude_data = json.loads(claude.read_text(encoding="utf-8"))
    assert claude_data["mcpServers"]["codeparse"] == {
        "command": str(fake_cli.resolve()),
        "args": ["mcp"],
    }


def test_install_mcp_cli_exits_one_when_nothing_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["codeparse", "mcp", "install"])
    monkeypatch.setattr("src.cli.install_mcp.install_mcp", list)
    assert main() == 1


def test_install_mcp_permission_error_prints_manual_entry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    cursor = tmp_path / "cursor.json"
    claude = tmp_path / "claude.json"
    cli = tmp_path / "codeparse"
    cli.write_text("x", encoding="utf-8")

    def boom(_self: Path, *_args: object, **_kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "write_text", boom)

    written = install_mcp(cli_path=cli, cursor_config=cursor, claude_config=claude)
    assert written == []
    err = capsys.readouterr().err
    assert "Warning: Could not write to" in err
    assert "Manually add this entry:" in err
    assert str(cli.resolve()) in err


def test_install_mcp_helper_writes_absolute_command(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cursor = tmp_path / "cursor.json"
    claude = tmp_path / "claude.json"
    cli = tmp_path / "bin" / "codeparse"
    cli.parent.mkdir()
    cli.write_text("x", encoding="utf-8")

    written = install_mcp(cli_path=cli, cursor_config=cursor, claude_config=claude)
    assert written == [cursor, claude]
    entry = json.loads(cursor.read_text(encoding="utf-8"))["mcpServers"]["codeparse"]
    assert entry["command"] == str(cli.resolve())
    assert entry["args"] == ["mcp", "--cwd", "${workspaceFolder}"]
    out = capsys.readouterr().out
    assert f"Wrote to {cursor}" in out


def test_resolve_cli_path_uses_argv_when_not_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "codeparse"
    binary.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(binary)])
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert resolve_cli_path() == binary.resolve()


def test_resolve_cli_path_uses_executable_when_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "codeparse-frozen"
    binary.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(binary))
    assert resolve_cli_path() == binary.resolve()


def test_cursor_and_claude_config_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    monkeypatch.setattr(install_mcp_mod.sys, "platform", "darwin")
    assert cursor_mcp_config_path() == home / ".cursor" / "mcp.json"
    assert "Application Support" in str(claude_desktop_config_path())

    monkeypatch.setattr(install_mcp_mod.sys, "platform", "linux")
    assert claude_desktop_config_path() == (
        home / ".config" / "Claude" / "claude_desktop_config.json"
    )

    monkeypatch.setattr(install_mcp_mod.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(home / "Roaming"))
    assert claude_desktop_config_path() == (
        home / "Roaming" / "Claude" / "claude_desktop_config.json"
    )

    monkeypatch.delenv("APPDATA", raising=False)
    assert "AppData" in str(claude_desktop_config_path())


def test_load_config_empty_and_invalid(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    assert _load_config(missing) == {}

    empty = tmp_path / "empty.json"
    empty.write_text("   \n", encoding="utf-8")
    assert _load_config(empty) == {}

    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(TypeError, match="not a JSON object"):
        _load_config(bad)


def test_merge_mcp_server_rejects_non_object_servers(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": []}), encoding="utf-8")
    with pytest.raises(TypeError, match="mcpServers must be an object"):
        merge_mcp_server(path, {"command": "codeparse"})


def test_create_skill_claude_writes_skill_md(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["codeparse", "create-skill", "claude", "--cwd", str(tmp_path)],
    )
    assert main() == 0
    out = capsys.readouterr().out
    skill_path = tmp_path / ".claude" / "skills" / "codeparse" / "SKILL.md"
    assert skill_path.is_file()
    assert str(skill_path) in out
    text = skill_path.read_text(encoding="utf-8")
    assert "get_file_overview" in text
    assert "get_symbol_context" in text
    assert "get_symbol_references" in text
    assert "find_importers" in text


def test_create_skill_cursor_writes_under_home(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["codeparse", "create-skill", "cursor"])
    assert main() == 0
    out = capsys.readouterr().out
    skill_path = tmp_path / ".cursor" / "skills" / "codeparse" / "SKILL.md"
    assert skill_path.is_file()
    assert str(skill_path) in out


def test_create_skill_claude_missing_cwd_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    missing = tmp_path / "gone"
    monkeypatch.setattr(
        sys,
        "argv",
        ["codeparse", "create-skill", "claude", "--cwd", str(missing)],
    )
    assert main() == 1
    assert "Not a directory" in capsys.readouterr().err


def test_index_incremental(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    (tmp_path / ".gitignore").write_text("# fixture\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["codeparse", "index", "--cwd", str(tmp_path)])
    assert main() == 0
    assert "Indexed" in capsys.readouterr().err


def test_index_full_reload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    (tmp_path / ".gitignore").write_text("# fixture\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["codeparse", "index", "--full-reload", "--cwd", str(tmp_path)]
    )
    assert main() == 0
    assert "Indexed" in capsys.readouterr().err


def test_index_missing_cwd_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    missing = tmp_path / "gone"
    monkeypatch.setattr(sys, "argv", ["codeparse", "index", "--cwd", str(missing)])
    assert main() == 1
    assert "Not a directory" in capsys.readouterr().err
