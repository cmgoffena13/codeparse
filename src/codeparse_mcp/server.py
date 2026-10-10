import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastmcp import Context, FastMCP

from src.codeparse_mcp.directory_tree import get_directory_tree as run_directory_tree
from src.codeparse_mcp.file_overview import get_file_overview as run_file_overview
from src.codeparse_mcp.find_importers import find_importers as run_find_importers
from src.codeparse_mcp.find_subclasses import find_subclasses as run_find_subclasses
from src.codeparse_mcp.project_overview import (
    get_project_overview as run_project_overview,
)
from src.codeparse_mcp.search_symbols import search_symbols as run_symbol_search
from src.codeparse_mcp.symbol_context import get_symbol_context as run_symbol_context
from src.codeparse_mcp.symbol_references import (
    get_symbol_references as run_symbol_references,
)
from src.db import CodeDB
from src.processor import CodeProcessor
from src.utils import get_code_parse_config_dir

_INSTRUCTIONS = """\
codeparse tools read an up-to-date view of the codebase.
Start the server in the repository you want to analyze.
Utilize the ``codeparse`` skill for the best results if available.

Current Supported File Languages: [Python]
"""


def index_root() -> Path:
    # Claude Desktop passes workspace via env var
    workspace = os.environ.get("CLAUDE_WORKSPACE", "").strip()
    if workspace:
        return Path(workspace).resolve()
    # VS Code / Terminal passes it via CWD
    return Path.cwd().resolve()


@asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncIterator[dict[str, Any]]:
    get_code_parse_config_dir()
    root = index_root()
    db = CodeDB(root)
    processor = CodeProcessor(db, root)
    processor.process()
    try:
        yield {"db": db, "processor": processor}
    finally:
        db.close()


mcp = FastMCP("codeparse", instructions=_INSTRUCTIONS, lifespan=_lifespan)


def _processor(ctx: Context) -> CodeProcessor:
    return ctx.lifespan_context["processor"]


@mcp.tool()
def get_project_overview(ctx: Context) -> str:
    """
    Return the top ten directories and all project entry points.
    """
    return _processor(ctx).run_query(run_project_overview)


@mcp.tool()
def get_directory_tree(ctx: Context, path: str | None = None) -> str:
    """
    Return the repo's directory/file tree with line and symbol counts.
    Optional ``path`` scopes to one directory tree (exact path).
    """
    return _processor(ctx).run_query(lambda db: run_directory_tree(db, path=path))


@mcp.tool()
def get_file_overview(file_path: str, ctx: Context) -> str:
    """
    Return imports and a nested symbol tree for one file with line numbers.
    Use ``get_symbol_context`` for code definitions.
    """
    path = file_path.strip()
    return _processor(ctx).run_query(lambda db: run_file_overview(db, path))


@mcp.tool()
def search_symbols(
    query: str,
    ctx: Context,
    limit: int = 10,
    include_tests: bool = False,
) -> str:
    """
    Full-text search across all symbols (``qualified_name``, signatures, and docstrings).
    Ranks results by text relevance to the query.
    Excludes test file symbols by default; set ``include_tests`` to include them.
    Use multiple keywords, separated by spaces, to narrow your search.
    Example queries: ``loader``, ``dialect format``
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
def get_symbol_context(qualified_name: str, ctx: Context) -> str:
    """
    Return the symbol code definition and aggregated count of reference sites
    (calls, accesses, type annotations).
    References do not follow multi-hop attribute access (obj.field.method) and untyped locals.
    Use ``get_symbol_references`` for detailed call, access, and type-annotation
    sites.
    """
    name = qualified_name.strip()
    return _processor(ctx).run_query(lambda db: run_symbol_context(db, name))


@mcp.tool()
def get_symbol_references(qualified_name: str, ctx: Context, include_tests: bool = False) -> str:
    """
    Return reference sites for a symbol (calls, accesses, type annotations) and
    which symbols they happen in.
    References do not follow multi-hop attribute access (obj.field.method) and untyped locals.
    Excludes test files by default; set ``include_tests`` to include them.
    """
    name = qualified_name.strip()
    return _processor(ctx).run_query(
        lambda db: run_symbol_references(db, name, include_tests=include_tests)
    )


@mcp.tool()
def find_subclasses(qualified_name: str, ctx: Context, include_tests: bool = False) -> str:
    """
    Return classes that directly inherit from a given class, with file and line.
    Excludes test files by default; set ``include_tests`` to include them.
    """
    name = qualified_name.strip()
    return _processor(ctx).run_query(
        lambda db: run_find_subclasses(db, name, include_tests=include_tests)
    )


@mcp.tool()
def find_importers(file_path: str, ctx: Context, include_tests: bool = False) -> str:
    """
    Return files that import a given module file.
    Excludes test files by default; set ``include_tests`` to include them.
    """
    path = file_path.strip()
    return _processor(ctx).run_query(
        lambda db: run_find_importers(db, path, include_tests=include_tests)
    )


def main() -> None:
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
