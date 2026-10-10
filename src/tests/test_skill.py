import asyncio
from pathlib import Path

from src.codeparse_mcp.skill import SKILL_INSTRUCTIONS, materialize_skill


def test_materialize_skill_writes_skill_md(tmp_path: Path) -> None:
    config = tmp_path / "codeparse"
    written = materialize_skill(config)
    assert written == config / "SKILL.md"
    assert written.read_text(encoding="utf-8") == SKILL_INSTRUCTIONS


def test_server_exposes_skill_resource() -> None:
    from src.codeparse_mcp.server import mcp

    resources = asyncio.run(mcp.list_resources())
    uris = {str(resource.uri) for resource in resources}
    assert "skill://codeparse/SKILL.md" in uris
    assert "skill://codeparse/_manifest" in uris
