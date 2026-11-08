"""Dependents (refs) and dependencies (invokes) for a symbol."""

from typing import Literal

from src.codeparse_mcp.symbol_invokes import get_symbol_invokes
from src.codeparse_mcp.symbol_references import get_symbol_references
from src.db import CodeDB


def get_symbol_links(
    db: CodeDB,
    qualified_name: str,
    *,
    direction: Literal["dependents", "dependencies"] = "dependents",
    include_tests: bool = False,
    reference_type: Literal["call", "access"] | None = None,
) -> str:
    """
    List links for ``qualified_name``.

    ``dependents`` lists symbols/files that reference it. ``dependencies`` lists
    symbols it invokes. ``include_tests`` applies only to dependents.
    ``reference_type`` may be ``call`` or ``access``; omit for both.
    """
    if direction == "dependencies":
        result = get_symbol_invokes(
            db,
            qualified_name,
            reference_type=reference_type,
        )
    else:
        result = get_symbol_references(
            db,
            qualified_name,
            include_tests=include_tests,
            reference_type=reference_type,
        )
    return result
