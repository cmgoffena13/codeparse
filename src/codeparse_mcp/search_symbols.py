import sqlite3
from collections import OrderedDict

from src.codeparse_mcp.format_utils import bullet
from src.db import CodeDB

_SYMBOL_SEARCH_SQL = """
SELECT
    s.qualified_name,
    s.line_start,
    s.line_end,
    f.path,
    bm25(symbols_fts, 10.0, 2.0) AS rank
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


_DROPPED_WORDS = frozenset({"def", "class", "async"})


def _strip_quotes(text: str) -> str:
    value = text.strip()
    quote = value[:1]
    if len(value) >= 2 and value[-1] == quote and quote in "\"'" and quote not in value[1:-1]:
        value = value[1:-1].strip()
    return value


def _fts_term(token: str) -> str:
    term = f'"{token.replace(chr(34), chr(34) * 2)}"'
    if token.isidentifier():
        term = token
    return term


def _word_clause(word: str) -> str:
    parts = [part for part in word.split(".") if part]
    clause = f"name: {_fts_term(word)}"
    if len(parts) >= 2:
        clause = f"parent: {_fts_term(parts[-2])} AND name: {_fts_term(parts[-1])}"
    return clause


def build_fts_query(user_input: str) -> str:
    """Turn free text into an OR of per-word column clauses.

    A word searches ``name`` as an exact token. ``parent`` is used only for a
    dotted word:
    ``parent: Context AND name: plan``. ``def``, ``class``, and ``async`` are
    dropped. ``bm25`` weights ``name`` above the other columns.
    """
    clauses = [
        _word_clause(word)
        for word in (_strip_quotes(part) for part in _strip_quotes(user_input).split())
        if word and word.lower() not in _DROPPED_WORDS
    ]
    query = ""
    if clauses:
        query = " OR ".join(clauses)
    return query


def search_symbols(
    db: CodeDB,
    query: str,
    limit: int,
    *,
    include_tests: bool,
) -> str:
    """
    Search symbols via ``symbols_fts`` (name, parent).

    Each word is its own OR clause. ``parent`` is queried only when the word
    contains a dot. A dotted word requires that parent and name.
    ``def``, ``class``, and ``async`` are dropped. Hyphens split into words.
    Returns hits grouped by file (files in BM25 order
    of first hit; symbols by line), each with rank ``#n``. By default skips
    ``is_test`` files; pass ``include_tests=True`` to include them.
    """
    stripped = query.strip().replace("-", " ")
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

    lines: list[str] = []
    rank_width = max(
        (len(str(rank)) for hits in by_path.values() for rank, *_rest in hits),
        default=1,
    )
    for path_index, (path, hits) in enumerate(by_path.items()):
        if path_index > 0:
            lines.append("")
        lines.append(path)
        ordered = sorted(hits, key=lambda item: (item[1], item[2], item[3]))
        for rank, _line_start, _line_end, qn in ordered:
            lines.append(bullet(qn, f"#{rank:<{rank_width}} "))

    return "\n".join(lines).rstrip() + "\n"
