import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.app import main
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


def test_install_registers_the_binary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import base64
    import json
    from urllib.parse import parse_qs, urlparse

    binary = tmp_path / "bin" / "codeparse"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    (tmp_path / ".cursor" / "skills").mkdir(parents=True)
    (tmp_path / "Library" / "Application Support" / "Claude").mkdir(parents=True)
    (tmp_path / ".config" / "goose").mkdir(parents=True)
    monkeypatch.setattr("src.cli.install_mcp.find_claude_command", lambda: "/usr/bin/claude")
    monkeypatch.setattr("src.cli.install_mcp.find_gemini_command", lambda: "/usr/bin/gemini")
    cli_calls: list[list[str]] = []
    monkeypatch.setattr(
        "src.cli.install_mcp.run_cli_command",
        lambda command: cli_calls.append(command),
    )
    deeplinks: list[str] = []
    monkeypatch.setattr(
        "src.cli.install_mcp.open_deeplink",
        lambda url, **_kwargs: deeplinks.append(url) or True,
    )
    monkeypatch.setattr(sys, "argv", [str(binary), "install"])

    assert main() == 0
    command = str(binary.resolve())
    claude = json.loads(
        (
            tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        ).read_text(encoding="utf-8")
    )
    assert not (tmp_path / ".cursor" / "mcp.json").exists()
    cursor_url = next(url for url in deeplinks if url.startswith("cursor://"))
    cursor_config = json.loads(
        base64.urlsafe_b64decode(parse_qs(urlparse(cursor_url).query)["config"][0])
    )
    assert cursor_config["command"] == command
    assert cursor_config["args"] == ["mcp"]
    assert claude["mcpServers"]["codeparse"]["command"] == command
    assert claude["mcpServers"]["codeparse"]["args"] == ["mcp"]
    assert cli_calls == [
        ["/usr/bin/claude", "mcp", "add", "codeparse", "--", command, "mcp"],
        ["/usr/bin/gemini", "mcp", "add", "codeparse", command, "--", "mcp"],
    ]
    assert any(url.startswith("cursor://") for url in deeplinks)
    assert any(url.startswith("goose://") for url in deeplinks)
    out = capsys.readouterr().out
    skill = tmp_path / ".cursor" / "skills" / "codeparse" / "SKILL.md"
    assert skill.is_file()
    assert f"Synced skill → {skill.parent}" in out
    assert "Restart the client" in out


def test_binary_path_uses_executable_when_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.cli.install_mcp import binary_path

    binary = tmp_path / "codeparse"
    binary.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(binary))
    monkeypatch.setattr(sys, "argv", ["codeparse", "install"])
    assert binary_path() == binary.resolve()


def test_binary_path_resolves_path_lookup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.cli.install_mcp import binary_path

    real = tmp_path / "real" / "codeparse"
    real.parent.mkdir()
    real.write_text("x", encoding="utf-8")
    link = tmp_path / "bin" / "codeparse"
    link.parent.mkdir()
    link.symlink_to(real)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "argv", ["codeparse", "install"])
    monkeypatch.setattr("src.cli.install_mcp.shutil.which", lambda _name: str(link))
    assert binary_path() == real.resolve()


def test_invalid_claude_config_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    binary = tmp_path / "codeparse"
    binary.write_text("x", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delattr(sys, "frozen", raising=False)
    claude_dir = tmp_path / "Library" / "Application Support" / "Claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "claude_desktop_config.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("src.cli.install_mcp.find_claude_command", lambda: None)
    monkeypatch.setattr("src.cli.install_mcp.find_gemini_command", lambda: None)
    monkeypatch.setattr(sys, "argv", [str(binary), "install"])

    assert main() == 1
    assert "Failed to install codeparse in Claude Desktop" in capsys.readouterr().err


def test_windows_deeplink_and_cmd_install(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastmcp.cli.install.shared import open_deeplink, run_cli_command

    monkeypatch.setattr(sys, "platform", "win32")
    opened: list[str] = []
    monkeypatch.setattr(os, "startfile", lambda url: opened.append(url), raising=False)
    assert open_deeplink("cursor://install", expected_scheme="cursor") is True
    assert opened == ["cursor://install"]

    recorded: dict[str, object] = {}

    def fake_run(command: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded["command"] = command
        recorded["executable"] = kwargs.get("executable")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("fastmcp.cli.install.shared.subprocess.run", fake_run)
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    run_cli_command(
        [
            r"C:\Users\me\AppData\Roaming\npm\claude.cmd",
            "mcp",
            "add",
            "codeparse",
            "--",
            r"C:\codeparse.exe",
            "mcp",
        ]
    )
    assert str(recorded["executable"]).lower().endswith("cmd.exe")
    assert "codeparse.exe" in str(recorded["command"])

    from fastmcp.cli.install.claude_code import find_claude_command

    def fake_version(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[0].endswith("claude.cmd")
        return subprocess.CompletedProcess(
            args=command, returncode=0, stdout="Claude Code 1.0\n", stderr=""
        )

    monkeypatch.setattr("fastmcp.cli.install.claude_code.subprocess.run", fake_version)
    monkeypatch.setattr(
        "fastmcp.cli.install.claude_code.shutil.which",
        lambda name: r"C:\npm\claude.cmd" if name == "claude" else None,
    )
    assert find_claude_command() == r"C:\npm\claude.cmd"


def test_install_with_no_clients_prints_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("src.cli.install_mcp.find_claude_command", lambda: None)
    monkeypatch.setattr("src.cli.install_mcp.find_gemini_command", lambda: None)
    monkeypatch.setattr(sys, "argv", ["codeparse", "install"])
    assert main() == 0
    assert "No MCP clients found." in capsys.readouterr().out


def test_install_mcp_cli_exits_one_when_nothing_written(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["codeparse", "install"])
    monkeypatch.setattr("src.cli.install_mcp.install_mcp", list)
    assert main() == 1


def test_sync_writes_only_existing_skill_dirs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".cursor" / "skills").mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["codeparse", "sync"])
    assert main() == 0
    out = capsys.readouterr().out
    cursor_skill = tmp_path / ".cursor" / "skills" / "codeparse" / "SKILL.md"
    assert cursor_skill.is_file()
    assert not (tmp_path / ".claude").exists()
    assert str(cursor_skill.parent) in out
    assert "get_symbol_context" in cursor_skill.read_text(encoding="utf-8")


def test_sync_with_no_skill_dirs_prints_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["codeparse", "sync"])
    assert main() == 0
    assert "No skill directories found." in capsys.readouterr().out


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
