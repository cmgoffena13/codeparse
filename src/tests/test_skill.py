import asyncio
from pathlib import Path

import yaml

from src.codeparse_mcp.skill import DESCRIPTION, SKILL_INSTRUCTIONS, materialize_skill, sync_skill


def test_frontmatter_description_parses() -> None:
    frontmatter, _, body = SKILL_INSTRUCTIONS.partition("\n---\n")
    parsed = yaml.safe_load(frontmatter.removeprefix("---\n"))
    assert parsed == {"name": "codeparse", "description": DESCRIPTION}
    assert body.lstrip("\n").startswith("IMPORTANT:")


def test_sync_skips_skill_when_hash_matches(monkeypatch, tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    skill_root.mkdir()
    monkeypatch.setattr("src.codeparse_mcp.skill.available_skill_dirs", lambda: [skill_root])

    assert sync_skill() == [skill_root / "codeparse"]
    written = skill_root / "codeparse" / "SKILL.md"
    stamp = written.stat().st_mtime_ns

    assert sync_skill() == []
    assert written.stat().st_mtime_ns == stamp
    assert written.read_text(encoding="utf-8") == SKILL_INSTRUCTIONS


def test_sync_rewrites_skill_when_hash_differs(monkeypatch, tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    skill_root.mkdir()
    monkeypatch.setattr("src.codeparse_mcp.skill.available_skill_dirs", lambda: [skill_root])
    sync_skill()
    written = skill_root / "codeparse" / "SKILL.md"
    written.write_text("stale", encoding="utf-8")

    assert sync_skill() == [skill_root / "codeparse"]
    assert written.read_text(encoding="utf-8") == SKILL_INSTRUCTIONS


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
