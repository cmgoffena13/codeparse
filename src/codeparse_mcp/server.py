import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastmcp import Context, FastMCP

from src.codeparse_mcp.directory_tree import get_directory_tree as run_directory_tree
from src.codeparse_mcp.entry_points import (
    get_entry_points as run_get_entry_points,
)
from src.codeparse_mcp.file_imports import get_file_imports as run_get_file_imports
from src.codeparse_mcp.file_symbols import get_file_symbols as run_get_file_symbols
from src.codeparse_mcp.list_importers import list_importers as run_list_importers
from src.codeparse_mcp.list_subclasses import list_subclasses as run_list_subclasses
from src.codeparse_mcp.search_symbols import search_symbols as run_symbol_search
from src.codeparse_mcp.session_stats import SessionStatsMiddleware, format_session_stats_report
from src.codeparse_mcp.skill import DESCRIPTION, materialize_skill
from src.codeparse_mcp.symbol import get_symbol as run_get_symbol
from src.codeparse_mcp.symbol_at_lines import get_symbol_at_lines as run_get_symbol_at_lines
from src.codeparse_mcp.symbol_links import get_symbol_links as run_get_symbol_links
from src.db import CodeDB
from src.processor import CodeProcessor
from src.utils import get_code_parse_config_dir

_INSTRUCTIONS = """\
codeparse tools read an up-to-date view of Python codebases.
Utilize the ``codeparse`` skill for guided exploration workflows.
Use the ``skill://codeparse/SKILL.md`` resource if the skill is not found.
"""


def index_root() -> Path:
    # Claude Desktop passes workspace via env var
    workspace = os.environ.get("CLAUDE_WORKSPACE", "").strip()
    if workspace:
        return Path(workspace).resolve()
    # VS Code / Terminal passes it via CWD
    return Path.cwd().resolve()


@asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncGenerator[dict[str, Any]]:
    get_code_parse_config_dir()
    root = index_root()
    db = CodeDB(root)
    processor: CodeProcessor = CodeProcessor(db, root)
    processor.process()
    try:
        yield {"db": db, "processor": processor}
    finally:
        db.close()


mcp = FastMCP("codeparse", instructions=_INSTRUCTIONS, lifespan=_lifespan)
mcp.add_middleware(SessionStatsMiddleware())
_SKILL_PATH = materialize_skill(get_code_parse_config_dir())


@mcp.resource(
    "skill://codeparse/SKILL.md",
    name="codeparse/SKILL.md",
    description=DESCRIPTION,
    mime_type="text/markdown",
)
def codeparse_skill() -> str:
    return _SKILL_PATH.read_text(encoding="utf-8")


@mcp.resource(
    "stats://codeparse/sessions",
    name="codeparse/sessions",
    description=(
        "Per MCP session (id + start time), a markdown table of files with "
        "tool_calls, latest_file_tokens, tool_output_tokens, and tokens_saved "
        "as a low-high range (once vs every re-read)."
    ),
    mime_type="text/markdown",
)
def session_stats_resource() -> str:
    return format_session_stats_report(index_root())


def _processor(ctx: Context) -> CodeProcessor:
    return ctx.lifespan_context["processor"]


@mcp.tool()
def get_entry_points(ctx: Context) -> str:
    """
    Returns all project entry points with line and symbol counts (lines L, symbols S).
    """
    return _processor(ctx).run_query(run_get_entry_points)


@mcp.tool()
def get_directory_tree(ctx: Context, path: str | None = None) -> str:
    """
    Return the repo's directory/file tree. Files are (lines L, symbols S).
    Optional ``path`` scopes to one directory tree (exact path).
    """
    return _processor(ctx).run_query(lambda db: run_directory_tree(db, path=path))


@mcp.tool()
def get_file_symbols(file_path: str, ctx: Context) -> str:
    """
    Return a nested symbol tree for one file with line numbers.
    Follow up with ``get_symbol`` for symbol definitions.
    """
    return _processor(ctx).run_query(lambda db: run_get_file_symbols(db, file_path))


@mcp.tool()
def get_file_imports(file_path: str, ctx: Context) -> str:
    """
    Return the import statements for one file with line numbers.
    Use ``list_importers`` with a dotted ``module_name`` to find dependents.
    """
    return _processor(ctx).run_query(lambda db: run_get_file_imports(db, file_path))


@mcp.tool()
def search_symbols(
    query: str,
    ctx: Context,
    limit: int = 10,
    include_tests: bool = False,
) -> str:
    """
    FTS symbol names. Results are grouped by file and ordered #1, #2, #3... by relevance.

    Excludes test file symbols by default; set ``include_tests`` to include them.
    Narrow with one distinctive word; Widen with extra space-separated words (OR).
    Example input queries: ``loader``, ``dialect format``, ``Context.plan``
    """
    return _processor(ctx).run_query(
        lambda db: run_symbol_search(
            db,
            query,
            limit,
            include_tests=include_tests,
        )
    )


@mcp.tool()
def get_symbol(qualified_name: str, ctx: Context, include_tests: bool = False) -> str:
    """
    Return the symbol definition with line numbers, inherited members,
    aggregated dependent counts, and dependency counts (calls, accesses).

    Excludes test dependents by default; set ``include_tests`` to include them.
    Links do not follow multi-hop attribute access (obj.field.method) and untyped locals.
    Use ``get_symbol_links`` for dependents (``direction="dependents"``) or
    dependencies (``direction="dependencies"``).
    """
    return _processor(ctx).run_query(
        lambda db: run_get_symbol(db, qualified_name, include_tests=include_tests)
    )


@mcp.tool()
def get_symbol_at_lines(
    file_path: str,
    line_start: int,
    ctx: Context,
    line_end: int | None = None,
    include_tests: bool = False,
) -> str:
    """
    Same output as ``get_symbol`` for the tightest symbol that contains the whole range.
    A range inside no single symbol returns each symbol and its line span.

    ``line_end`` defaults to ``line_start`` if not provided.
    Excludes test dependents by default; set ``include_tests`` to include them.
    """
    return _processor(ctx).run_query(
        lambda db: run_get_symbol_at_lines(
            db, file_path, line_start, line_end, include_tests=include_tests
        )
    )


@mcp.tool()
def get_symbol_links(
    qualified_name: str,
    ctx: Context,
    direction: Literal["dependents", "dependencies"] = "dependents",
    reference_type: Literal["call", "access"] | None = None,
    include_tests: bool = False,
) -> str:
    """
    Return linked symbols for ``qualified_name``.

    ``direction="dependents"`` lists who references it; ``direction="dependencies"``
    lists what it invokes. Grouped by file. A dependent site with no enclosing symbol
    shows its line number.

    Links do not follow multi-hop attribute access (obj.field.method) and untyped locals.
    For dependents, excludes test files by default; set ``include_tests`` to include them.
    ``include_tests`` does not filter dependencies.
    Set ``reference_type`` to ``call`` or ``access`` to return only one kind.
    """
    return _processor(ctx).run_query(
        lambda db: run_get_symbol_links(
            db,
            qualified_name,
            direction=direction,
            include_tests=include_tests,
            reference_type=reference_type,
        )
    )


@mcp.tool()
def list_subclasses(qualified_name: str, ctx: Context, include_tests: bool = False) -> str:
    """
    Return classes that directly inherit from a given class, grouped by file.
    Excludes test files by default; set ``include_tests`` to include them.
    """
    return _processor(ctx).run_query(
        lambda db: run_list_subclasses(db, qualified_name, include_tests=include_tests)
    )


@mcp.tool()
def list_importers(
    module_name: str,
    ctx: Context,
    include_tests: bool = False,
) -> str:
    """
    Return a directory tree of files that import a module.
    ``module_name`` is a dotted path like ``sqlglot`` or ``pydantic.core``.
    Excludes test files by default; set ``include_tests`` to include them.
    """
    return _processor(ctx).run_query(
        lambda db: run_list_importers(db, module_name, include_tests=include_tests)
    )


def main() -> None:
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
