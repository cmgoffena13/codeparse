"""Register the codeparse binary with every MCP client FastMCP knows about."""

import json
import os
import subprocess
import sys
from pathlib import Path

from fastmcp.cli.install.claude_code import find_claude_command
from fastmcp.cli.install.claude_desktop import get_claude_config_path
from fastmcp.cli.install.cursor import generate_cursor_deeplink
from fastmcp.cli.install.gemini_cli import find_gemini_command
from fastmcp.cli.install.goose import generate_goose_deeplink
from fastmcp.cli.install.shared import open_deeplink, run_cli_command
from fastmcp.mcp_config import MCPConfig, StdioMCPServer, update_config_file

from src.utils import binary_path

SERVER_NAME = "codeparse"


def _goose_config_dir() -> Path:
    """Same directory FastMCP's Goose installer and discovery use."""
    if sys.platform == "win32":
        return Path(
            os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"),
            "Block",
            "goose",
            "config",
        )
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"), "goose")


def _server(cli: Path) -> StdioMCPServer:
    return StdioMCPServer(command=str(cli), args=["mcp"], type="stdio")


def install_mcp() -> list[str] | None:
    """Install the codeparse binary into each FastMCP client that is present.

    FastMCP's ``install_*`` helpers launch a Python file with ``uv``. This CLI
    is the compiled binary, so each client is given that executable instead.

    Returns the client names that were installed, or ``None`` when no client
    is installed.
    """
    cli = binary_path()
    server = _server(cli)
    installed: list[str] = []
    saw_client = False

    cursor_dir = Path.home() / ".cursor"
    if cursor_dir.is_dir():
        saw_client = True
        if open_deeplink(generate_cursor_deeplink(SERVER_NAME, server), expected_scheme="cursor"):
            installed.append("cursor")

    claude_dir = get_claude_config_path()
    if claude_dir is not None:
        saw_client = True
        config_file = claude_dir / "claude_desktop_config.json"
        try:
            if config_file.is_file() and config_file.read_text(encoding="utf-8").strip():
                update_config_file(config_file, SERVER_NAME, server)
            else:
                MCPConfig(mcpServers={SERVER_NAME: server}).write_to_file(config_file)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"Failed to install codeparse in Claude Desktop: {exc}", file=sys.stderr)
        else:
            installed.append("claude-desktop")

    claude_cmd = find_claude_command()
    if claude_cmd:
        saw_client = True
        try:
            run_cli_command([claude_cmd, "mcp", "add", SERVER_NAME, "--", str(cli), "mcp"])
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Failed to install codeparse in Claude Code: {exc}", file=sys.stderr)
        else:
            installed.append("claude-code")

    gemini_cmd = find_gemini_command()
    if gemini_cmd:
        saw_client = True
        try:
            run_cli_command([gemini_cmd, "mcp", "add", SERVER_NAME, str(cli), "--", "mcp"])
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Failed to install codeparse in Gemini CLI: {exc}", file=sys.stderr)
        else:
            installed.append("gemini-cli")

    if _goose_config_dir().is_dir():
        saw_client = True
        deeplink = generate_goose_deeplink(SERVER_NAME, str(cli), ["mcp"])
        if open_deeplink(deeplink, expected_scheme="goose"):
            installed.append("goose")

    if not saw_client:
        return None
    return installed


def _drop_server(data: dict[str, object]) -> bool:
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or SERVER_NAME not in servers:
        return False
    del servers[SERVER_NAME]
    return True


def _remove_from_mcp_json(path: Path) -> bool | None:
    """Remove ``codeparse`` from an MCP JSON config.

    Returns ``True`` when an entry was removed, ``False`` when the file has no
    entry, and ``None`` when the file could not be updated.
    """
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to uninstall codeparse from {path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"Failed to uninstall codeparse from {path}: not a JSON object", file=sys.stderr)
        return None
    removed = _drop_server(data)
    projects = data.get("projects")
    if isinstance(projects, dict):
        for project in projects.values():
            if isinstance(project, dict):
                removed = _drop_server(project) or removed
    if not removed:
        return False
    try:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"Failed to uninstall codeparse from {path}: {exc}", file=sys.stderr)
        return None
    print(f"Removed codeparse from {path}")
    return True


def _remove_goose() -> bool | None:
    path = _goose_config_dir() / "config.yaml"
    if not path.is_file():
        return False
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"Failed to uninstall codeparse from {path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        return False
    extensions = data.get("extensions")
    if not isinstance(extensions, dict) or SERVER_NAME not in extensions:
        return False
    del extensions[SERVER_NAME]
    try:
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    except OSError as exc:
        print(f"Failed to uninstall codeparse from {path}: {exc}", file=sys.stderr)
        return None
    print(f"Removed codeparse from {path}")
    return True


def _remove_via_cli(command: list[str], client: str) -> None:
    try:
        run_cli_command(command)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Failed to uninstall codeparse from {client}: {exc}", file=sys.stderr)


def uninstall_mcp() -> bool:
    """Remove the codeparse MCP server from installed clients.

    Returns ``False`` when a config file could not be updated.
    """
    ok = True
    removed = False
    home = Path.home()
    configs = [
        home / ".cursor" / "mcp.json",
        home / ".claude.json",
        home / ".gemini" / "settings.json",
    ]
    claude_dir = get_claude_config_path()
    if claude_dir is not None:
        configs.append(claude_dir / "claude_desktop_config.json")
    for path in configs:
        result = _remove_from_mcp_json(path)
        if result is None:
            ok = False
        removed = removed or result is True

    claude_cmd = find_claude_command()
    if claude_cmd:
        for scope in ("user", "local"):
            _remove_via_cli(
                [claude_cmd, "mcp", "remove", SERVER_NAME, "--scope", scope],
                "Claude Code",
            )
    gemini_cmd = find_gemini_command()
    if gemini_cmd:
        _remove_via_cli([gemini_cmd, "mcp", "remove", SERVER_NAME], "Gemini CLI")

    goose = _remove_goose()
    if goose is None:
        ok = False
    removed = removed or goose is True
    if not removed:
        print("No MCP server entries found.")
    return ok
