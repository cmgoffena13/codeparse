"""Module-level dependents and dependencies via symbol references."""

from collections import OrderedDict
from typing import Literal

from src.codeparse_mcp.format_utils import (
    kind_count_suffix,
    page_footer,
    page_window,
    tree_glyphs,
)
from src.db import EXTERNAL_PACKAGES_FILE_ID, CodeDB

_MAX_ROWS = 100

_RESOLVE_DIRECTORY_SQL = """
SELECT id FROM directories WHERE path = ?
"""

_FILE_IDS_FOR_MODULE_SQL = """
SELECT id, normalized_path FROM files
WHERE id != ?
  AND (normalized_path = ? OR normalized_path LIKE ?)
ORDER BY normalized_path
"""

_FILE_IDS_UNDER_DIRECTORY_SQL = """
SELECT id FROM files
WHERE id != ?
  AND (path = ? OR path LIKE ?)
ORDER BY path
"""

_ROWS_SQL = """
SELECT
    f.path AS source_path,
    sr.source_symbol_qualified_name AS source_qualified_name,
    sr.ref_symbol_qualified_name AS target_qualified_name,
    sr.ref_kind AS ref_kind
FROM symbol_references AS sr
INNER JOIN files AS f
    ON f.id = sr.source_file_id
WHERE sr.ref_kind != 'type_annotation'
{scope_filter}
{test_filter}
ORDER BY f.path, sr.source_line, sr.ref_symbol_qualified_name, sr.ref_kind
"""


def _prefix_params(module: str) -> tuple[str, str]:
    return module, f"{module}.%"


def _resolve_file_ids(db: CodeDB, target: str) -> tuple[str, list[int] | None]:
    kind = "external"
    file_ids: list[int] | None = None
    module_rows = list(
        db.connection.execute(
            _FILE_IDS_FOR_MODULE_SQL,
            (EXTERNAL_PACKAGES_FILE_ID, *_prefix_params(target)),
        )
    )
    if module_rows:
        if len(module_rows) == 1 and module_rows[0]["normalized_path"] == target:
            kind = "file"
            file_ids = [int(module_rows[0]["id"])]
        else:
            kind = "directory"
            file_ids = [int(row["id"]) for row in module_rows]
    else:
        dir_path = target.replace(".", "/")
        directory = db.connection.execute(_RESOLVE_DIRECTORY_SQL, (dir_path,)).fetchone()
        if directory is not None:
            kind = "directory"
            file_ids = [
                int(row["id"])
                for row in db.connection.execute(
                    _FILE_IDS_UNDER_DIRECTORY_SQL,
                    (EXTERNAL_PACKAGES_FILE_ID, f"{dir_path}/__init__.py", f"{dir_path}/%"),
                )
            ]
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


def _source_tree_lines(
    module: str,
    sources: OrderedDict[str, None],
    targets_by_source: OrderedDict[str, OrderedDict[str, dict[str, int]]],
) -> list[str]:
    children: dict[str | None, list[str]] = {}
    ordered_sources = list(sources)
    if "(module)" in sources:
        rest = [source_qn for source_qn in sources if source_qn != "(module)"]
        ordered_sources = ["(module)", *rest]
    for source_qn in ordered_sources:
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
            connector, stem = tree_glyphs(is_last)
            lines.append(f"{prefix}{connector}{node}")
            child_prefix = prefix + stem
            if node in targets_by_source:
                for target_qn, kind_counts in targets_by_source[node].items():
                    lines.append(f"{child_prefix}   • {target_qn}{kind_count_suffix(kind_counts)}")
            lines.extend(branch(node, child_prefix))
        return lines

    return branch(None, "  ")


def _flat_source_lines(
    sources: OrderedDict[str, OrderedDict[str, dict[str, int]]],
) -> list[str]:
    ordered_sources = list(sources)
    if "(module)" in sources:
        ordered_sources = ["(module)"] + [qn for qn in sources if qn != "(module)"]
    lines: list[str] = []
    for source_index, source_qn in enumerate(ordered_sources):
        if source_index > 0:
            lines.append("")
        lines.append(source_qn)
        for target_qn, kind_counts in sources[source_qn].items():
            lines.append(f"  • {target_qn}{kind_count_suffix(kind_counts)}")
    return lines


def _format_relation_rows(rows: list, *, show_file_paths: bool, flat: bool) -> str:
    by_file: OrderedDict[str, OrderedDict[str, OrderedDict[str, dict[str, int]]]] = OrderedDict()
    for row in rows:
        path = row["source_path"]
        source_qn = row["source_qualified_name"] or "(module)"
        target_qn = row["target_qualified_name"]
        kind = row["ref_kind"]
        sources = by_file.setdefault(path, OrderedDict())
        targets = sources.setdefault(source_qn, OrderedDict())
        kind_counts = targets.get(target_qn)
        if kind_counts is None:
            kind_counts = {}
            targets[target_qn] = kind_counts
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    lines: list[str] = []
    for file_index, (path, sources) in enumerate(by_file.items()):
        if show_file_paths:
            if file_index > 0:
                lines.append("")
            lines.append(path)
        elif file_index > 0:
            lines.append("")
        if flat:
            lines.extend(_flat_source_lines(sources))
        else:
            source_keys = OrderedDict((source_qn, None) for source_qn in sources)
            lines.extend(_source_tree_lines(_module_from_path(path), source_keys, sources))
    return "\n".join(lines).strip() + "\n"


def _format_rows(
    rows: list,
    *,
    relation: Literal["dependents", "dependencies"],
    page: int = 1,
    show_file_paths: bool = True,
) -> str:
    total = len(rows)
    window = page_window(total, page, _MAX_ROWS, label=relation)
    result: str
    if isinstance(window, str):
        result = window
    else:
        start, stop, page_count = window
        shown = rows[start:stop]
        body = _format_relation_rows(
            shown,
            show_file_paths=show_file_paths,
            flat=relation == "dependencies" and not show_file_paths,
        )
        result = body
        if page_count > 1:
            result = (
                body.rstrip("\n")
                + "\n\n"
                + page_footer(page, page_count, len(shown), total, relation)
                + "\n"
            )
    return result


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
    page: int = 1,
) -> str:
    """
    List call/access relations for a dotted module path.

    Resolves ``target`` as an internal directory, internal file, or external
    package. ``dependents`` lists who uses its symbols; ``dependencies`` lists
    what its files use. ``include_tests`` applies only to dependents.
    ``page`` is 1-indexed over relation rows.
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
            result = (
                _format_rows(rows, relation=relation, page=page)
                if rows
                else "No import relations found."
            )
        elif not file_ids:
            result = "No import relations found."
        elif relation == "dependencies":
            rows = _query_rows(
                db,
                (
                    _dependencies_scope(file_ids)
                    + "\n  AND sr.ref_symbol_id IS NOT NULL"
                    + "\n  AND sr.ref_symbol_file_id != ?"
                    + "\n  AND sr.ref_symbol_file_id != sr.source_file_id"
                ),
                [*file_ids, EXTERNAL_PACKAGES_FILE_ID],
                include_tests=True,
            )
            result = (
                _format_rows(rows, relation=relation, page=page, show_file_paths=kind != "file")
                if rows
                else "No import relations found."
            )
        else:
            rows = _query_rows(
                db,
                _dependents_scope(file_ids),
                list(file_ids),
                include_tests,
            )
            result = (
                _format_rows(rows, relation=relation, page=page)
                if rows
                else "No import relations found."
            )
    return result
