"""Reverse-import lookup: which files import a given module."""

from src.codeparse_mcp.paths import normalize_repo_file_path
from src.db import CodeDB

_MAX_IMPORTER_FILES = 100

_IMPORTERS_SQL = """
SELECT DISTINCT 
f.path AS importer_path
FROM imports AS i
INNER JOIN files AS f
    ON f.id = i.file_id
INNER JOIN files AS target
    ON target.id = i.imported_file_id
WHERE target.path = ?
{test_filter}
ORDER BY f.path
"""


def list_importers(db: CodeDB, file_path: str, *, include_tests: bool) -> str:
    """
    List files that import the module at ``file_path`` as a directory tree.

    ``file_path`` is a repo-relative file path (e.g. ``pkg/mod.py``). Matching
    is by ``imports.imported_file_id``.

    By default skips importer files marked ``is_test``.
    """
    result = ""
    try:
        path = normalize_repo_file_path(file_path, db.root)
    except ValueError as exc:
        result = str(exc)
    else:
        rows = list(
            db.connection.execute(
                _IMPORTERS_SQL.format(test_filter="" if include_tests else "  AND f.is_test = 0"),
                (path,),
            )
        )
        if not rows:
            result = "No importers found."
        else:
            paths = [row["importer_path"] for row in rows]
            result = _format_importers(paths)
    return result


def _format_importers(paths: list[str]) -> str:
    total = len(paths)
    shown = paths[:_MAX_IMPORTER_FILES]
    lines_out = _tree_lines(_tree(shown), "")
    header = f"Total Files: {total}"
    if total > _MAX_IMPORTER_FILES:
        header = f"Showing {len(shown)} of {total} files"
    lines_out.insert(0, header)
    lines_out.insert(1, "")
    return "\n".join(lines_out).rstrip() + "\n"


def _tree(paths: list[str]) -> dict:
    root: dict = {}
    for path in paths:
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = None
    return root


def _tree_lines(node: dict, prefix: str) -> list[str]:
    names = sorted(node, key=lambda name: (node[name] is None, name.lower()))
    last_index = len(names) - 1
    lines: list[str] = []
    for index, name in enumerate(names):
        connector = "└── " if index == last_index else "├── "
        child = node[name]
        if isinstance(child, dict):
            lines.append(f"{prefix}{connector}{name}/")
            continuation = "    " if index == last_index else "│   "
            lines.extend(_tree_lines(child, prefix + continuation))
        else:
            lines.append(f"{prefix}{connector}{name}")
    return lines
