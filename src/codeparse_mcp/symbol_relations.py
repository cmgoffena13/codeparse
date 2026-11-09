"""Dependents (refs) and dependencies (invokes) for a symbol."""

from typing import Literal

from src.codeparse_mcp.symbol_invokes import get_symbol_invokes
from src.codeparse_mcp.symbol_references import get_symbol_references
from src.db import CodeDB


def get_symbol_relations(
    db: CodeDB,
    qualified_name: str,
    *,
    relation: Literal["dependents", "dependencies"] = "dependents",
    include_tests: bool = False,
    page: int = 1,
) -> str:
    """
    List relations for ``qualified_name``.

    ``dependents`` lists symbols/files that reference it. ``dependencies`` lists
    symbols it invokes. ``include_tests`` applies only to dependents.
    ``page`` is 1-indexed over symbols.
    """
    if relation == "dependencies":
        result = get_symbol_invokes(db, qualified_name, page=page)
    else:
        result = get_symbol_references(
            db,
            qualified_name,
            include_tests=include_tests,
            page=page,
        )
    return result
