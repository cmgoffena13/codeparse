import sqlite3
from collections import OrderedDict

from src.codeparse_mcp.format_utils import line_span
from src.db import CodeDB

_SYMBOL_SEARCH_SQL = """
SELECT
    s.qualified_name,
    s.line_start,
    s.line_end,
    f.path AS path,
    bm25(symbols_fts, 10.0, 5.0, 5.0) AS rank
FROM symbols_fts
INNER JOIN symbols AS s
    ON s.id = symbols_fts.rowid
INNER JOIN files AS f
    ON f.id = s.file_id
WHERE symbols_fts MATCH ?
{test_filter}
ORDER BY rank
LIMIT ?
"""


def build_fts_query(user_input: str) -> str:
    """Turn free text into an AND of prefix terms (e.g. ``auth login`` → ``auth* AND login*``).

    Tokens are always AND'd. Do not treat ``AND``/``OR``/``NOT`` in the input as
    FTS operators — they become ordinary terms.
    """
    terms = user_input.split()
    if not terms:
        return ""
    return " AND ".join(f"{term}*" for term in terms)


def search_symbols(
    db: CodeDB,
    query: str,
    limit: int = 10,
    *,
    include_tests: bool = False,
) -> str:
    """
    Search symbols via ``symbols_fts`` (qualified_name, signature,
    docstring). Repo-wide only — use ``get_file_overview`` to map one file.

    Query is space-separated phrases/terms, OR'd with prefix matching. Returns
    hits grouped by file (files in BM25 order of first hit; symbols by line),
    each with rank ``#n`` and line span for ``get_symbol``. By default
    skips ``is_test`` files; pass ``include_tests=True`` to include them.
    """
    stripped = query.strip().replace("-", " ")
    if not stripped:
        return "No search text given; pass a non-empty query."

    fts_query = build_fts_query(stripped)
    if not fts_query:
        return "No search text given; pass a non-empty query."

    try:
        rows = db.connection.execute(
            _SYMBOL_SEARCH_SQL.format(
                test_filter="" if include_tests else "  AND f.is_test = 0",
            ),
            (fts_query, limit),
        ).fetchall()
    except sqlite3.OperationalError as e:
        return f"Search failed for {query!r} ({fts_query!r}): {e}"

    by_path: OrderedDict[str, list[tuple[int, int, int, str]]] = OrderedDict()
    for rank, row in enumerate(rows, start=1):
        path = row["path"] or "(unknown path)"
        qn = (row["qualified_name"] or "").strip()
        if not qn:
            continue
        by_path.setdefault(path, []).append(
            (rank, int(row["line_start"] or 0), int(row["line_end"] or 0), qn)
        )

    lines: list[str] = [
        "Legend: # = Rank, L = Line\n",
        f'Search results for "{stripped}" ({len(rows)} matches)',
        "",
    ]
    for path_index, (path, hits) in enumerate(by_path.items()):
        if path_index > 0:
            lines.append("")
        lines.append(path)
        ordered = sorted(hits, key=lambda item: (item[1], item[2], item[3]))
        for rank, line_start, line_end, qn in ordered:
            loc = line_span(line_start, line_end)
            lines.append(f"  • #{rank} {loc}  {qn}")

    return "\n".join(lines).rstrip() + "\n"
