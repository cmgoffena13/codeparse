"""Drive the codeparse MCP server through FastMCP's client."""

import asyncio
from pathlib import Path

import mcp_types
import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from src.codeparse_mcp.skill import SKILL_INSTRUCTIONS

_PROJECT = Path(__file__).resolve().parent / "test_project"
_TOOLS = {
    "list_subclasses",
    "get_directory_tree",
    "get_file_symbol_tree",
    "get_entry_points",
    "get_import_relations",
    "get_symbol",
    "get_symbol_at_lines",
    "get_symbol_links",
    "search_symbols",
}


def _text(result: CallToolResult) -> str:
    assert result.is_error is False
    assert isinstance(result.data, str)
    return result.data


def _resource_text(
    contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
) -> str:
    block = contents[0]
    assert isinstance(block, mcp_types.TextResourceContents)
    return block.text


def test_client_lists_tools_and_reads_skill(
    mcp_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(_PROJECT))

    async def run() -> None:
        async with mcp_client:
            tools = await mcp_client.list_tools()
            assert {tool.name for tool in tools} == _TOOLS

            skill = _resource_text(await mcp_client.read_resource("skill://codeparse/SKILL.md"))
            assert skill == SKILL_INSTRUCTIONS

    asyncio.run(run())


def test_client_tools_read_the_workspace(
    mcp_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(_PROJECT))

    async def run() -> None:
        async with mcp_client:
            tree = _text(await mcp_client.call_tool("get_directory_tree", {"path": "pkg"}))
            assert "child.py" in tree
            assert "tests/test_child.py" not in tree

            file_symbols = _text(
                await mcp_client.call_tool("get_file_symbol_tree", {"file_path": "pkg/child.py"})
            )
            assert "pkg.child.Child" in file_symbols
            assert "from pkg.base import Parent" not in file_symbols
            assert "## Imports" not in file_symbols

            found = _text(
                await mcp_client.call_tool("search_symbols", {"query": "Child", "limit": 5})
            )
            assert "pkg.child.Child" in found
            assert "TestChild" not in found

            context = _text(
                await mcp_client.call_tool("get_symbol", {"qualified_name": "pkg.child.Child"})
            )
            assert "## Code Definition" not in context
            assert "class Child(Parent):" in context

            references = _text(
                await mcp_client.call_tool(
                    "get_symbol_links", {"qualified_name": "pkg.base.Parent"}
                )
            )
            assert "pkg/user.py" in references
            assert "tests/test_child.py" not in references

            with_tests = _text(
                await mcp_client.call_tool(
                    "get_symbol_links",
                    {"qualified_name": "pkg.base.Parent", "include_tests": True},
                )
            )
            assert "tests/test_child.py" in with_tests

            subclasses = _text(
                await mcp_client.call_tool("list_subclasses", {"qualified_name": "pkg.base.Parent"})
            )
            assert "pkg.child.Child" in subclasses
            assert "TestChild" not in subclasses

            relations = _text(
                await mcp_client.call_tool("get_import_relations", {"target": "pkg.base"})
            )
            assert "pkg/child.py" in relations or "pkg/user.py" in relations
            assert "tests/test_child.py" not in relations

    asyncio.run(run())
