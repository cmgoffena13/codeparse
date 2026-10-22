from collections import defaultdict

from src.codeparse_mcp.format_utils import line_span
from src.codeparse_mcp.indexed_file import load_indexed_file
from src.db import CodeDB

_SYMBOLS_SQL = """
SELECT
    id,
    parent_id,
    kind,
    qualified_name,
    line_start,
    line_end
FROM symbols
WHERE file_id = ?
ORDER BY line_start, line_end, qualified_name
"""


def _symbol_label(row) -> str:
    loc = line_span(int(row["line_start"]), int(row["line_end"]))
    kind = (row["kind"] or "").strip()
    label = row["qualified_name"].strip()
    return f"{loc}  {kind}  {label}"


def _symbol_branch_lines(
    children_by_parent_id: dict[int | None, list],
    parent_id: int | None,
    branch_prefix: str,
) -> list[str]:
    lines: list[str] = []
    siblings = children_by_parent_id.get(parent_id, ())
    last_i = len(siblings) - 1
    for index, row in enumerate(siblings):
        is_last = index == last_i
        connector = "└─ " if is_last else "├─ "
        lines.append(f"{branch_prefix}{connector}{_symbol_label(row)}")
        continuation = "   " if is_last else "│  "
        lines.extend(
            _symbol_branch_lines(children_by_parent_id, row["id"], branch_prefix + continuation)
        )
    return lines


def get_file_symbols(db: CodeDB, file_path: str) -> str:
    """
    Return a nested symbol tree for one file.

    Symbols use ``L{start}[-{end}]  kind  qualified_name``. ``file_path`` is
    normalized to a POSIX path relative to the workspace root (e.g. ``pkg/mod.py``).
    """
    error, file_row = load_indexed_file(db, file_path)
    result = error
    if file_row is not None:
        sym_rows = list(db.connection.execute(_SYMBOLS_SQL, (file_row["id"],)))
        lines_out: list[str] = [
            f"Total Lines: {file_row['line_count']}",
            f"Total Symbols: {len(sym_rows)}",
            "",
        ]
        if not sym_rows:
            lines_out.append("_(none)_")
        else:
            ids_in_file = {r["id"] for r in sym_rows}

            def effective_parent_id(row) -> int | None:
                pid = row["parent_id"]
                if pid is None:
                    return None
                if pid not in ids_in_file:
                    return None
                return pid

            children_by_parent_id: dict[int | None, list] = defaultdict(list)
            for row in sym_rows:
                children_by_parent_id[effective_parent_id(row)].append(row)
            for bucket in children_by_parent_id.values():
                bucket.sort(key=lambda r: (r["line_start"], r["line_end"], r["qualified_name"]))

            roots = children_by_parent_id.get(None, ())
            for root_index, row in enumerate(roots):
                if root_index > 0:
                    lines_out.append("")
                lines_out.append(_symbol_label(row))
                lines_out.extend(_symbol_branch_lines(children_by_parent_id, row["id"], ""))
        result = "\n".join(lines_out) + "\n"
    return result
