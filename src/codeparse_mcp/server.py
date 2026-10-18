import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastmcp import Context, FastMCP

from src.codeparse_mcp.directory_tree import get_directory_tree as run_directory_tree
from src.codeparse_mcp.file_overview import get_file_overview as run_file_overview
from src.codeparse_mcp.list_importers import list_importers as run_list_importers
from src.codeparse_mcp.list_subclasses import list_subclasses as run_list_subclasses
from src.codeparse_mcp.project_overview import (
    get_project_overview as run_project_overview,
)
from src.codeparse_mcp.search_symbols import search_symbols as run_symbol_search
from src.codeparse_mcp.skill import DESCRIPTION, materialize_skill, skill_manifest
from src.codeparse_mcp.symbol_at_lines import get_symbol_at_lines as run_symbol_at_lines
from src.codeparse_mcp.symbol_context import get_symbol_context as run_symbol_context
from src.codeparse_mcp.symbol_references import (
    get_symbol_references as run_symbol_references,
)
from src.db import CodeDB
from src.processor import CodeProcessor
from src.utils import get_code_parse_config_dir

_INSTRUCTIONS = """\
codeparse tools read an up-to-date view of Python codebases.
Utilize the ``codeparse`` skill for guided exploration workflows.
"""


def index_root() -> Path:
    # Claude Desktop passes workspace via env var
    workspace = os.environ.get("CLAUDE_WORKSPACE", "").strip()
    if workspace:
        return Path(workspace).resolve()
    # VS Code / Terminal passes it via CWD
    return Path.cwd().resolve()


@asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
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
    "skill://codeparse/_manifest",
    name="codeparse/_manifest",
    description="File listing for codeparse",
    mime_type="application/json",
)
def codeparse_skill_manifest() -> str:
    return skill_manifest(_SKILL_PATH.read_bytes())


def _processor(ctx: Context) -> CodeProcessor:
    return ctx.lifespan_context["processor"]


@mcp.tool()
def get_project_overview(ctx: Context) -> str:
    """
    Return the top ten directories by symbol count and all project entry points.
    Directories are (lines L, symbols S, files F) and entry points are (lines L, symbols S).
    """
    return _processor(ctx).run_query(run_project_overview)


@mcp.tool()
def get_directory_tree(ctx: Context, path: str | None = None) -> str:
    """
    Return the repo's directory/file tree. Files are (lines L, symbols S).
    Optional ``path`` scopes to one directory tree (exact path).
    """
    return _processor(ctx).run_query(lambda db: run_directory_tree(db, path=path))


@mcp.tool()
def get_file_overview(file_path: str, ctx: Context) -> str:
    """
    Return imports and a nested symbol tree for one file with line numbers.
    Follow up with ``get_symbol`` for symbol definitions.
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
    Full-text search across all symbols (``qualified_name``, signatures, docstrings, and modifiers),
    grouped by file. Results are ordered #1, #2, #3 by relevance.

    Excludes test file symbols by default; set ``include_tests`` to include them.
    Narrow with one distinctive word; Widen with extra space-separated words (OR).
    Example input queries: ``loader``, ``dialect format``
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
def get_symbol(qualified_name: str, ctx: Context) -> str:
    """
    Return the symbol definition with line numbers and aggregated reference counts,
    split into references and test references (calls, accesses, type annotations).

    References do not follow multi-hop attribute access (obj.field.method) and untyped locals.
    Use ``get_symbol_references`` for detailed call, access, and type-annotation sites.
    """
    name = qualified_name.strip()
    return _processor(ctx).run_query(lambda db: run_symbol_context(db, name))


@mcp.tool()
def get_symbol_at_lines(
    file_path: str,
    line_start: int,
    ctx: Context,
    line_end: int | None = None,
) -> str:
    """
    Same output as ``get_symbol`` for the tightest symbol containing the range
    (a method, not its class). A range inside no single symbol returns each symbol
    and its line span.

    ``line_end`` defaults to ``line_start`` if not provided.
    """
    path = file_path.strip()
    return _processor(ctx).run_query(lambda db: run_symbol_at_lines(db, path, line_start, line_end))


@mcp.tool()
def get_symbol_references(qualified_name: str, ctx: Context, include_tests: bool = False) -> str:
    """
    Return reference sites (calls, accesses, type annotations) for a symbol, grouped by file
    and the symbol they happen in. A site with no enclosing symbol shows its line number.

    References do not follow multi-hop attribute access (obj.field.method) and untyped locals.
    Excludes test files by default; set ``include_tests`` to include them.
    """
    name = qualified_name.strip()
    return _processor(ctx).run_query(
        lambda db: run_symbol_references(db, name, include_tests=include_tests)
    )


@mcp.tool()
def list_subclasses(qualified_name: str, ctx: Context, include_tests: bool = False) -> str:
    """
    Return classes that directly inherit from a given class, grouped by file.
    Excludes test files by default; set ``include_tests`` to include them.
    """
    name = qualified_name.strip()
    return _processor(ctx).run_query(
        lambda db: run_list_subclasses(db, name, include_tests=include_tests)
    )


@mcp.tool()
def list_importers(file_path: str, ctx: Context, include_tests: bool = False) -> str:
    """
    Return a directory tree of files that import a given module file.
    Excludes test files by default; set ``include_tests`` to include them.
    """
    path = file_path.strip()
    return _processor(ctx).run_query(
        lambda db: run_list_importers(db, path, include_tests=include_tests)
    )


def main() -> None:
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
