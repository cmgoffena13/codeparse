"""Module-level dependents and dependencies via symbol references."""

from collections import OrderedDict
from typing import Literal

from src.db import EXTERNAL_PACKAGES_FILE_ID, CodeDB

_MAX_ROWS = 100

_RESOLVE_DIRECTORY_SQL = """
SELECT id FROM directories WHERE path = ?
"""

_FILE_IDS_FOR_MODULE_SQL = """
SELECT id FROM files
WHERE normalized_path = ?
   OR normalized_path LIKE ?
"""

_FILE_ID_SQL = """
SELECT id FROM files WHERE normalized_path = ?
"""

_ROWS_SQL = """
SELECT
    f.path AS source_path,
    src.qualified_name AS source_qualified_name,
    sr.ref_symbol_qualified_name AS target_qualified_name,
    sr.ref_kind AS ref_kind
FROM symbol_references AS sr
INNER JOIN files AS f
    ON f.id = sr.source_file_id
LEFT JOIN symbols AS src
    ON src.id = sr.source_symbol_id
WHERE sr.ref_kind != 'type_annotation'
{scope_filter}
{test_filter}
ORDER BY sr.ref_symbol_qualified_name, sr.ref_kind, f.path, src.qualified_name
"""


def _prefix_params(module: str) -> tuple[str, str]:
    return module, f"{module}.%"


def _resolve_file_ids(db: CodeDB, target: str) -> tuple[str, list[int] | None]:
    dir_path = target.replace(".", "/")
    directory = db.connection.execute(_RESOLVE_DIRECTORY_SQL, (dir_path,)).fetchone()
    kind = "external"
    file_ids: list[int] | None = None
    if directory is not None:
        kind = "directory"
        file_ids = [
            int(row["id"])
            for row in db.connection.execute(_FILE_IDS_FOR_MODULE_SQL, _prefix_params(target))
        ]
    else:
        file_row = db.connection.execute(_FILE_ID_SQL, (target,)).fetchone()
        if file_row is not None:
            kind = "file"
            file_ids = [int(file_row["id"])]
    return kind, file_ids


def _test_filter(include_tests: bool) -> str:
    return "" if include_tests else "  AND f.is_test = 0"


def _module_from_path(path: str) -> str:
    stem = path.removesuffix(".py")
    stem = stem.removesuffix("/__init__")
    return stem.replace("/", ".")


def _source_parent(module: str, source_qn: str, sources: OrderedDict[str, None]) -> str | None:
    parent = None
    if source_qn != "(module)" and source_qn.startswith(f"{module}."):
        parts = source_qn[len(module) + 1 :].split(".")
        for depth in range(len(parts) - 1, 0, -1):
            candidate = f"{module}.{'.'.join(parts[:depth])}"
            if candidate in sources:
                parent = candidate
                break
    return parent


def _source_tree_lines(module: str, sources: OrderedDict[str, None]) -> list[str]:
    children: dict[str | None, list[str]] = {}
    for source_qn in sources:
        parent = _source_parent(module, source_qn, sources)
        bucket = children.setdefault(parent, [])
        if source_qn not in bucket:
            bucket.append(source_qn)

    def branch(parent: str | None, prefix: str) -> list[str]:
        items = children.get(parent, [])
        lines: list[str] = []
        last_i = len(items) - 1
        for index, node in enumerate(items):
            is_last = index == last_i
            connector = "└─ " if is_last else "├─ "
            continuation = "   " if is_last else "│  "
            lines.append(f"{prefix}{connector}{node}")
            lines.extend(branch(node, prefix + continuation))
        return lines

    return branch(None, "  ")


def _format_rows(rows: list) -> str:
    truncated = len(rows) > _MAX_ROWS
    shown = rows[:_MAX_ROWS]
    by_target: OrderedDict[tuple[str, str], OrderedDict[str, OrderedDict[str, None]]] = (
        OrderedDict()
    )
    counts: dict[tuple[str, str], int] = {}
    for row in shown:
        kind = row["ref_kind"][0].upper()
        key = (row["target_qualified_name"], kind)
        path = row["source_path"]
        source_qn = row["source_qualified_name"] or "(module)"
        counts[key] = counts.get(key, 0) + 1
        files = by_target.setdefault(key, OrderedDict())
        sources = files.setdefault(path, OrderedDict())
        sources[source_qn] = None

    lines: list[str] = []
    for target_index, (key, files) in enumerate(by_target.items()):
        if target_index > 0:
            lines.append("")
        target_qn, kind = key
        lines.append(f"{target_qn} ({kind}) ({counts[key]})")
        for path, sources in files.items():
            lines.append(f"• {path}")
            lines.extend(_source_tree_lines(_module_from_path(path), sources))

    if truncated:
        lines.extend(["", f"… truncated to {_MAX_ROWS} references"])
    return "\n".join(lines).strip() + "\n"


def _query_rows(db: CodeDB, scope_filter: str, params: list, include_tests: bool) -> list:
    return list(
        db.connection.execute(
            _ROWS_SQL.format(
                scope_filter=scope_filter,
                test_filter=_test_filter(include_tests),
            ),
            params,
        )
    )


def _file_id_placeholders(file_ids: list[int]) -> str:
    return ", ".join("?" for _ in file_ids)


def _dependents_scope(file_ids: list[int]) -> str:
    placeholders = _file_id_placeholders(file_ids)
    return (
        "  AND sr.ref_symbol_id IN (SELECT s.id FROM symbols AS s "  # noqa: S608
        "WHERE s.file_id IN (" + placeholders + "))"
    )


def _dependencies_scope(file_ids: list[int]) -> str:
    placeholders = _file_id_placeholders(file_ids)
    return "  AND sr.source_file_id IN (" + placeholders + ")"


def get_import_relations(
    db: CodeDB,
    target: str,
    *,
    relation: Literal["dependents", "dependencies"] = "dependents",
    include_tests: bool = False,
) -> str:
    """
    List call/access relations for a dotted module path.

    Resolves ``target`` as an internal directory, internal file, or external
    package. ``dependents`` lists who uses its symbols; ``dependencies`` lists
    what its files use. ``include_tests`` applies only to dependents.
    """
    key = target.strip()
    result = "No target given; pass a non-empty dotted module path."
    if key:
        kind, file_ids = _resolve_file_ids(db, key)
        if kind == "external" and relation == "dependencies":
            result = "External package dependencies are not available."
        elif kind == "external":
            module, module_like = _prefix_params(key)
            rows = _query_rows(
                db,
                "  AND sr.ref_symbol_id IN (\n"
                "    SELECT s.id FROM symbols AS s\n"
                "    WHERE s.file_id = ?\n"
                "      AND (s.qualified_name = ? OR s.qualified_name LIKE ?)\n"
                "  )",
                [EXTERNAL_PACKAGES_FILE_ID, module, module_like],
                include_tests,
            )
            result = _format_rows(rows) if rows else "No import relations found."
        elif not file_ids:
            result = "No import relations found."
        elif relation == "dependencies":
            rows = _query_rows(
                db,
                _dependencies_scope(file_ids),
                list(file_ids),
                include_tests=True,
            )
            result = _format_rows(rows) if rows else "No import relations found."
        else:
            rows = _query_rows(
                db,
                _dependents_scope(file_ids),
                list(file_ids),
                include_tests,
            )
            result = _format_rows(rows) if rows else "No import relations found."
    return result
