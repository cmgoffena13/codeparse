import os
import sys
from pathlib import Path

from src.cli.commands import build_arg_parser, make_parser
from src.utils import get_code_parse_config_dir, get_version


def _require_dir(path: Path) -> Path | None:
    resolved = path.resolve()
    if not resolved.is_dir():
        print(f"Not a directory: {resolved}", file=sys.stderr)
        return None
    return resolved


def _require_indexable_root(path: Path) -> Path | None:
    root = _require_dir(path)
    if root is None:
        return None
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        print(
            f".gitignore not found at {gitignore}; are you in a git repository?",
            file=sys.stderr,
        )
        return None
    return root


def _run_reload(root: Path) -> int:
    from src.db import CodeDB
    from src.processor import CodeProcessor

    db = CodeDB(root)
    try:
        db.recreate_schema()
        CodeProcessor(db, root).process(full=True)
    finally:
        db.close()
    return 0


def _run_mcp(root: Path) -> int:
    os.chdir(root)
    from src.codeparse_mcp.server import mcp

    mcp.run(transport="stdio", show_banner=False)
    return 0


def main() -> int:
    args = build_arg_parser()
    if args.info:
        cli_path = Path(sys.argv[0]).resolve()
        print(f"Binary path: {cli_path}")
        print(f"Config directory: {get_code_parse_config_dir()}")
        return 0
    if args.version:
        print(f"codeparse version: {get_version()}")
        return 0
    if args.command == "sync":
        from src.codeparse_mcp.skill import sync_skill

        sync_skill()
        return 0
    if args.command == "reload":
        root = _require_indexable_root(args.cwd)
        if root is None:
            return 1
        return _run_reload(root)
    if args.command == "install":
        from src.cli.install_mcp import install_mcp
        from src.codeparse_mcp.skill import sync_skill

        installed = install_mcp()
        sync_skill()
        if installed is None:
            print("No MCP clients found.")
            return 0
        if not installed:
            return 1
        print("Restart the client (or reload MCP) to pick up the change.")
        return 0
    if args.command == "uninstall":
        from src.cli.install_mcp import uninstall_mcp
        from src.codeparse_mcp.skill import remove_skill

        ok = uninstall_mcp()
        remove_skill()
        return 0 if ok else 1
    if args.command == "upgrade":
        from src.cli.upgrade import upgrade

        return upgrade()
    if args.command == "mcp":
        root = _require_indexable_root(args.cwd)
        if root is None:
            return 1
        return _run_mcp(root)

    make_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
