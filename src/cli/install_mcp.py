"""Register the codeparse binary with every MCP client FastMCP knows about."""

import json
import os
import shutil
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

SERVER_NAME = "codeparse"


def binary_path() -> Path:
    """Absolute path to this codeparse executable.

    A frozen build uses ``sys.executable``. ``sys.argv[0]`` is only the name
    the shell used, which is a bare PATH entry or a symlink.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    invoked = Path(sys.argv[0])
    if not invoked.is_absolute():
        found = shutil.which(sys.argv[0])
        if found:
            invoked = Path(found)
    return invoked.resolve()


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
