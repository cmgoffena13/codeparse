from collections import defaultdict

from src.codeparse_mcp.format_utils import line_span
from src.codeparse_mcp.paths import normalize_repo_file_path
from src.db import CodeDB

_SYMBOLS_SQL = """
SELECT
    id,
    parent_id,
    kind,
    qualified_name,
    name,
    line_start,
    line_end
FROM symbols
WHERE file_id = ?
ORDER BY line_start, line_end, qualified_name
"""

_IMPORTS_SQL = """
SELECT
    line_number,
    signature
FROM imports
WHERE file_id = ?
ORDER BY line_number
"""


def _gutter_width(*line_numbers: int) -> int:
    positives = [n for n in line_numbers if n > 0]
    if not positives:
        return 1
    return len(str(max(positives)))


def _symbol_label(row) -> str:
    loc = line_span(int(row["line_start"]), int(row["line_end"]))
    kind = (row["kind"] or "").strip()
    label = (row["qualified_name"] or row["name"] or "").strip()
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


def get_file_overview(db: CodeDB, file_path: str) -> str:
    """
    Return imports and a nested symbol tree for one file.

    Imports use a padded ``L{n}`` gutter (same idea as ``get_symbol``).
    Symbols use ``L{start}[-{end}]  kind  qualified_name``. ``file_path`` is
    normalized to a POSIX path relative to the workspace root (e.g. ``pkg/mod.py``).
    """
    try:
        path = normalize_repo_file_path(file_path, db.root)
    except ValueError as exc:
        return str(exc)

    file_row = db.connection.execute(
        "SELECT id, path, line_count FROM files WHERE path = ?",
        (path,),
    ).fetchone()
    if file_row is None:
        return f"No file matches {path!r}."

    file_id = file_row["id"]
    imp_rows = list(db.connection.execute(_IMPORTS_SQL, (file_id,)))
    sym_rows = list(db.connection.execute(_SYMBOLS_SQL, (file_id,)))

    lines_out: list[str] = [
        "Legend: L = Line\n",
        f"File: {file_row['path']}",
        f"Lines: {file_row['line_count']}",
        "",
        f"## Imports ({len(imp_rows)})",
        "",
    ]
    if not imp_rows:
        lines_out.append("_(none)_")
    else:
        # One DB row per imported name from `from m import a, b` repeats the same
        # statement `signature`; show each distinct signature once (first line).
        seen_signatures: set[str] = set()
        import_lines: list[tuple[int, str]] = []
        for row in imp_rows:
            line_n = int(row["line_number"] or 0)
            sig = (row["signature"] or "").strip() or "—"
            if sig != "—" and sig in seen_signatures:
                continue
            if sig != "—":
                seen_signatures.add(sig)
            import_lines.append((line_n, sig))
        gutter = _gutter_width(*(n for n, _ in import_lines), int(file_row["line_count"] or 0))
        for line_n, sig in import_lines:
            if line_n > 0:
                lines_out.append(f"L{line_n:<{gutter}}  {sig}")
            else:
                lines_out.append(sig)

    lines_out.extend(["", f"## Symbols ({len(sym_rows)})", ""])

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

    return "\n".join(lines_out) + "\n"
