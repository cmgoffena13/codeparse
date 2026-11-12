import argparse
from pathlib import Path

_HELP_BANNER = """\
  ____          _      ____                     
 / ___|___   __| | ___|  _ \\ __ _ _ __ ___  ___ 
| |   / _ \\ / _` |/ _ \\ |_) / _` | '__/ __|/ _ \\
| |__| (_) | (_| |  __/  __/ (_| | |  \\__ \\  __/
 \\____\\___/ \\__,_|\\___|_|   \\__,_|_|  |___/\\___|
""".replace("`", "'")


def help_banner() -> str:
    return _HELP_BANNER


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codeparse",
        description=help_banner(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show CLI version",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Show CLI information",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "install",
        help="Register codeparse in installed MCP clients and write the skill",
    )
    subparsers.add_parser(
        "uninstall",
        help="Remove the codeparse MCP server, skill, and indexes",
    )
    update_parser = subparsers.add_parser(
        "update",
        help="Replace this binary with a GitHub release and update the skill",
    )
    update_parser.add_argument(
        "--version",
        dest="release_version",
        default=None,
        help="Release to install (e.g. 0.12.0 or v0.12.0); default is latest",
    )

    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Start the MCP server",
    )
    mcp_parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Workspace root to index (default: current directory)",
    )

    reload_parser = subparsers.add_parser(
        "reload",
        help="Drop the index and reprocess the workspace",
    )
    reload_parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Workspace root to index (default: current directory)",
    )

    return parser


def build_arg_parser(argv: list[str] | None = None) -> argparse.Namespace:
    return make_parser().parse_args(argv)
