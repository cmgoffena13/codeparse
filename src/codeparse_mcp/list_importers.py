"""Reverse-import lookup: which files import a given module."""

from src.db import CodeDB

_MAX_IMPORTER_FILES = 100

_IMPORTERS_SQL = """
SELECT DISTINCT
f.path AS importer_path
FROM imports AS i
INNER JOIN files AS f
    ON f.id = i.file_id
WHERE (
    i.import_path = ?
    OR i.module = ?
)
{test_filter}
ORDER BY f.path
"""


def list_importers(
    db: CodeDB,
    module_name: str,
    *,
    include_tests: bool,
) -> str:
    """
    List files that import a module as a directory tree.

    ``module_name`` is a dotted path such as ``sqlglot`` or ``pkg.target``.
    Matches ``import_path`` or top-level ``module``.
    Use ``get_symbol_references`` for symbol-level import/use sites.

    By default skips importer files marked ``is_test``.
    """
    module_arg = module_name.strip()
    result = "No module name given; pass a non-empty module_name."
    if module_arg:
        test_filter = "" if include_tests else "  AND f.is_test = 0"
        rows = list(
            db.connection.execute(
                _IMPORTERS_SQL.format(test_filter=test_filter),
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
