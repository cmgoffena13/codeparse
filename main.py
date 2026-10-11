"""Smoke-print MCP tool outputs against the eval SQLMesh checkout."""

import asyncio
import json
import os
from pathlib import Path

import mcp_types
from fastmcp import Client
from fastmcp.client.client import CallToolResult

REPO_ROOT = Path(__file__).resolve().parent
SQLMESH_ROOT = REPO_ROOT / "eval" / "cache" / "sqlmesh"

_BANNER_WIDTH = 40


def _banner(title: str) -> str:
    label = f" {title} "
    pad = max(_BANNER_WIDTH - len(label), 0)
    left = pad // 2
    right = pad - left
    return f"{'-' * left}{label}{'-' * right}"


def _print_section(title: str, body: str) -> None:
    print(_banner(title))
    print(body)
    print(f"[{len(body):,} chars / {body.count(chr(10)) + 1} lines]\n")


def _body(result: CallToolResult) -> str:
    if not isinstance(result.data, str):
        raise SystemExit(f"Tool returned no text: {result.content}")
    return result.data


def _resource_text(
    contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
) -> str:
    block = contents[0]
    if not isinstance(block, mcp_types.TextResourceContents):
        raise SystemExit(f"Resource returned a blob: {block}")
    return block.text


def _server_preamble(client: Client) -> str:
    info = client.server_info
    header = "unknown" if info is None else f"{info.name} {info.version}".strip()
    return f"{header}\n\n{client.instructions or ''}".rstrip() + "\n"


def _format_tools(tools: list[mcp_types.Tool]) -> str:
    parts: list[str] = []
    for tool in tools:
        block = (
            f"{tool.name}\n{(tool.description or '').strip()}\n"
            f"input:\n{json.dumps(tool.input_schema, indent=2)}"
        )
        if tool.output_schema is not None:
            block += f"\noutput:\n{json.dumps(tool.output_schema, indent=2)}"
        parts.append(block)
    return "\n\n".join(parts) + "\n"


def _format_resources(resources: list[mcp_types.Resource]) -> str:
    if not resources:
        return "No resources.\n"
    parts: list[str] = []
    for resource in resources:
        parts.append(
            "\n".join(
                [
                    str(resource.uri),
                    f"name: {resource.name}",
                    f"mime: {resource.mime_type}",
                    f"description: {resource.description or ''}",
                ]
            )
        )
    return "\n\n".join(parts) + "\n"


def _format_prompts(prompts: list[mcp_types.Prompt]) -> str:
    if not prompts:
        return "No prompts.\n"
    parts: list[str] = []
    for prompt in prompts:
        parts.append(f"{prompt.name}\n{(prompt.description or '').strip()}")
    return "\n\n".join(parts) + "\n"


async def _print_catalog(client: Client) -> None:
    _print_section("SERVER", _server_preamble(client))
    _print_section("TOOLS", _format_tools(await client.list_tools()))
    resources = await client.list_resources()
    _print_section("RESOURCES", _format_resources(resources))
    for resource in resources:
        _print_section(
            str(resource.uri),
            _resource_text(await client.read_resource(resource.uri)),
        )
    _print_section("PROMPTS", _format_prompts(await client.list_prompts()))


async def _print_tools() -> None:
    os.environ["CLAUDE_WORKSPACE"] = str(SQLMESH_ROOT)
    from src.codeparse_mcp.server import mcp

    async with Client(mcp) as client:
        await _print_catalog(client)
        _print_section(
            "DIRECTORY TREE",
            _body(await client.call_tool("get_directory_tree", {"path": "sqlmesh/core/"})),
        )
        _print_section(
            "FILE OVERVIEW",
            _body(
                await client.call_tool(
                    "get_file_overview", {"file_path": "sqlmesh/core/dialect.py"}
                )
            ),
        )
        _print_section(
            "SEARCH SYMBOLS",
            _body(
                await client.call_tool(
                    "search_symbols",
                    {"query": "format_model", "include_tests": True},
                )
            ),
        )
        _print_section(
            "SYMBOL CONTEXT",
            _body(
                await client.call_tool(
                    "get_symbol",
                    {"qualified_name": "sqlmesh.RuntimeEnv.is_terminal"},
                )
            ),
        )
        _print_section(
            "SYMBOL REFERENCES",
            _body(
                await client.call_tool(
                    "get_symbol_references",
                    {
                        "qualified_name": ("sqlmesh.RuntimeEnv.is_terminal"),
                        "include_tests": True,
                    },
                )
            ),
        )
        _print_section(
            "FIND IMPORTERS",
            _body(
                await client.call_tool(
                    "find_importers",
                    {"file_path": "sqlmesh/core/dialect.py", "include_tests": True},
                )
            ),
        )
        _print_section(
            "FIND SUBCLASSES",
            _body(
                await client.call_tool(
                    "find_subclasses",
                    {"qualified_name": "sqlmesh.core.snapshot.evaluator.EvaluationStrategy"},
                )
            ),
        )
        _print_section(
            "PROJECT OVERVIEW",
            _body(await client.call_tool("get_project_overview")),
        )


def main() -> None:
    if not SQLMESH_ROOT.is_dir():
        raise SystemExit(f"Missing {SQLMESH_ROOT}; run an eval smoke first to clone sqlmesh.")
    asyncio.run(_print_tools())


if __name__ == "__main__":
    main()
