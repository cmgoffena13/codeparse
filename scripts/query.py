"""Probe an indexed tree the same way MCP/eval tools would.

Examples:
  uv run scripts/query.py search_symbols format_model
  uv run scripts/query.py search_symbols "dialect format" --limit 20
  uv run scripts/query.py sql "SELECT count(*) FROM symbols"
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.codeparse_mcp.search_symbols import search_symbols
from src.db import CodeDB
from src.utils import db_path_for_index_root

DEFAULT_ROOT = REPO_ROOT / "eval" / "cache" / "sqlmesh"


def _open_db(root: Path, *, reindex: bool) -> CodeDB:
    db_file = db_path_for_index_root(root)
    if not db_file.exists() and not reindex:
        raise SystemExit(
            f"No index at {db_file}\nIndex first (codeparse reload --cwd {root}) or pass --reindex."
        )
    db = CodeDB(root)
    if reindex:
        from src.processor import CodeProcessor

        CodeProcessor(db, root).process(full=True)
    return db


def _cmd_search_symbols(db: CodeDB, args: argparse.Namespace) -> int:
    print(
        search_symbols(
            db,
            args.query,
            args.limit,
            include_tests=args.include_tests,
        ),
        end="",
    )
    return 0


def _cmd_sql(db: CodeDB, args: argparse.Namespace) -> int:
    cur = db.connection.execute(args.statement)
    rows = cur.fetchall()
    if cur.description:
        print(" | ".join(col[0] for col in cur.description))
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))
    print(f"({len(rows)} rows)", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"Indexed workspace root (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Full reindex before running the command",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    ss = sub.add_parser(
        "search_symbols",
        help="Same output as the MCP search_symbols tool",
    )
    ss.add_argument("query", help='FTS query, e.g. "format_model" or "dialect format"')
    ss.add_argument("--limit", type=int, default=10)
    ss.add_argument(
        "--include-tests",
        action="store_true",
        help="Include is_test files (MCP default is false)",
    )
    ss.set_defaults(func=_cmd_search_symbols)

    sql = sub.add_parser("sql", help="Run a raw SQL statement against the index DB")
    sql.add_argument("statement")
    sql.set_defaults(func=_cmd_sql)

    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    db = _open_db(root, reindex=args.reindex)
    try:
        return args.func(db, args)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
