"""Reverse-import lookup: which files import a given module."""

from src.codeparse_mcp.paths import normalize_repo_file_path
from src.db import CodeDB

_MAX_IMPORTER_FILES = 100

_IMPORTERS_BY_PATH_SQL = """
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

_IMPORTERS_BY_MODULE_SQL = """
SELECT DISTINCT
f.path AS importer_path
FROM imports AS i
INNER JOIN files AS f
    ON f.id = i.file_id
WHERE (
    i.module = ?
    OR i.import_path = ?
)
{test_filter}
ORDER BY f.path
"""


def list_importers(
    db: CodeDB,
    file_path: str | None = None,
    *,
    module_name: str | None = None,
    include_tests: bool,
) -> str:
    """
    List files that import a module as a directory tree.

    Pass exactly one of ``file_path`` (repo-relative module file) or
    ``module_name`` (dotted import path such as ``sqlglot`` or ``pkg.target``).
    ``file_path`` matches via ``imports.imported_file_id``; ``module_name``
    matches ``imports.module`` (top-level) or ``import_path`` (dotted).

    By default skips importer files marked ``is_test``.
    """
    path_arg = None if file_path is None else file_path.strip() or None
    module_arg = None if module_name is None else module_name.strip() or None
    result = "Provide exactly one of file_path or module_name."
    if (path_arg is None) != (module_arg is None):
        test_filter = "" if include_tests else "  AND f.is_test = 0"
        if path_arg is not None:
            try:
                path = normalize_repo_file_path(path_arg, db.root)
            except ValueError as exc:
                result = str(exc)
            else:
                rows = list(
                    db.connection.execute(
                        _IMPORTERS_BY_PATH_SQL.format(test_filter=test_filter),
                        (path,),
                    )
                )
                result = _format_importers([row["importer_path"] for row in rows])
        else:
            rows = list(
                db.connection.execute(
                    _IMPORTERS_BY_MODULE_SQL.format(test_filter=test_filter),
                    (module_arg, module_arg),
                )
            )
            result = _format_importers([row["importer_path"] for row in rows])
    return result


def _format_importers(paths: list[str]) -> str:
    result = "No importers found."
    if paths:
        total = len(paths)
        shown = paths[:_MAX_IMPORTER_FILES]
        lines_out = _tree_lines(_tree(shown), "")
        header = f"Total Files: {total}"
        if total > _MAX_IMPORTER_FILES:
            header = f"Showing {len(shown)} of {total} files"
        lines_out.insert(0, header)
        lines_out.insert(1, "")
        result = "\n".join(lines_out).rstrip() + "\n"
    return result


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
