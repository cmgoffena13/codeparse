from collections import defaultdict

from src.codeparse_mcp.format_utils import file_label
from src.codeparse_mcp.paths import normalize_repo_file_path
from src.db import CodeDB

_TREE_SQL = """
SELECT
    'directory' AS row_type,
    id,
    parent_id,
    name,
    NULL AS line_count,
    NULL AS symbol_count
FROM directories
UNION ALL
SELECT
    'file' AS row_type,
    id,
    directory_id AS parent_id,
    name,
    line_count,
    symbol_count
FROM files
"""

# Paths under one directory. ``path`` is unique, so the bounds are an index range.
# ``pkg/core/`` through ``pkg/core0`` is every path under ``pkg/core``, because
# ``/`` is the byte immediately before ``0``.
_SUBTREE_SQL = """
SELECT
    'directory' AS row_type,
    id,
    parent_id,
    name,
    NULL AS line_count,
    NULL AS symbol_count
FROM directories
WHERE path >= ? AND path < ?
UNION ALL
SELECT
    'file' AS row_type,
    id,
    directory_id AS parent_id,
    name,
    line_count,
    symbol_count
FROM files
WHERE path >= ? AND path < ?
"""


def _children_by_parent(rows):
    children_by_parent_id = defaultdict(list)
    for row in rows:
        is_directory = row["row_type"] == "directory"
        children_by_parent_id[row["parent_id"]].append((is_directory, row))
    for sibling_list in children_by_parent_id.values():
        sibling_list.sort(
            key=lambda item: (not item[0], item[1]["name"].lower()),
        )
    return children_by_parent_id


def _render(children_by_parent_id, root_key, root_label: str) -> str:
    body_lines = _lines_under_parent(children_by_parent_id, root_key, "")
    if not body_lines:
        return root_label.rstrip("/") or "."
    return root_label + "\n" + "\n".join(body_lines)


def _lines_under_parent(children_by_parent_id, parent_key, branch_prefix):
    lines = []
    siblings = children_by_parent_id.get(parent_key, ())
    last_index = len(siblings) - 1
    for index, (is_directory, row) in enumerate(siblings):
        is_last_child = index == last_index
        connector = "└── " if is_last_child else "├── "
        if is_directory:
            display_name = row["name"] + "/"
        else:
            display_name = file_label(
                row["name"],
                row["line_count"] or 0,
                row["symbol_count"] if row["symbol_count"] is not None else 0,
            )
        lines.append(f"{branch_prefix}{connector}{display_name}")
        if is_directory:
            continuation = "    " if is_last_child else "│   "
            next_prefix = branch_prefix + continuation
            lines.extend(_lines_under_parent(children_by_parent_id, row["id"], next_prefix))
    return lines


def get_directory_tree(db: CodeDB, path: str | None) -> str:
    """
    Return the directory/file tree with line and symbol counts.

    Optional ``path`` scopes to one directory tree (exact path).
    """
    scoped = None
    if path and path.strip():
        try:
            normalized = normalize_repo_file_path(path, db.root).rstrip("/")
        except ValueError as exc:
            return str(exc)
        if normalized not in ("", "."):
            scoped = normalized

    if scoped is None:
        rows = db.connection.execute(_TREE_SQL)
        return _render(_children_by_parent(rows), None, ".")

    dir_row = db.connection.execute(
        "SELECT id, path FROM directories WHERE path = ?",
        (scoped,),
    ).fetchone()
    if dir_row is None:
        return f"No directory matches {scoped!r}."

    prefix = f"{dir_row['path']}/"
    upper = f"{dir_row['path']}0"
    rows = db.connection.execute(_SUBTREE_SQL, (prefix, upper, prefix, upper))
    return _render(_children_by_parent(rows), dir_row["id"], f"{dir_row['path']}/")
