import argparse
from pathlib import Path


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codeparse", description="codeparse")
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
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Workspace root (default: current directory)",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "sync",
        help="Update the codeparse skill in existing skill directories",
    )
    subparsers.add_parser(
        "install",
        help="Register codeparse in installed MCP clients and write the skill",
    )
    subparsers.add_parser(
        "uninstall",
        help="Remove the codeparse MCP server and skill",
    )
    subparsers.add_parser(
        "upgrade",
        help="Replace this binary with the latest release and update the skill",
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
