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


def _run_index(root: Path, *, full: bool) -> int:
    from src.db import CodeDB
    from src.processor import CodeProcessor

    db = CodeDB(root)
    try:
        CodeProcessor(db, root).process(full=full)
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
        print(f"CLI Path: {cli_path}")
        print(f"Config Directory: {get_code_parse_config_dir()}")
        return 0
    if args.version:
        print(f"codeparse Version: {get_version()}")
        return 0
    if args.command == "create-skill":
        from src.codeparse_mcp.skill import generate_skill

        if args.target == "claude":
            root = _require_dir(args.cwd)
            if root is None:
                return 1
            path = generate_skill("claude", root=root)
        else:
            path = generate_skill("cursor")
        print(f"Wrote skill → {path}")
        return 0
    if args.command == "index":
        root = _require_indexable_root(args.cwd)
        if root is None:
            return 1
        return _run_index(root, full=args.full_reload)
    if args.command == "mcp":
        if getattr(args, "mcp_command", None) == "install":
            from src.cli.install_mcp import install_mcp

            written = install_mcp()
            if written:
                print("Restart the client (or reload MCP) to pick up the change.")
                return 0
            return 1
        root = _require_indexable_root(args.cwd)
        if root is None:
            return 1
        return _run_mcp(root)

    make_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
