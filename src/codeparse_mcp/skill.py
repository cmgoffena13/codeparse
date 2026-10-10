import hashlib
import json
from pathlib import Path

import yaml

DESCRIPTION = (
    "Use when navigating a Python codebase: locating definitions/references, "
    "mapping repo structure, getting file summaries, or understanding how "
    "files and symbols depend on each other. "
    "Covers symbol search and entry points."
)

_SKILL_BODY = """\
IMPORTANT: ALWAYS USE ``get_file_overview`` / ``get_symbol`` instead of \
``read`` to get file / symbol information.

The information that is provided to you will determine the tool you should use.

## You are given the file name.
1. Use ``get_file_overview`` to get a summary of the symbols in the file.
2. Use ``get_symbol`` to get the code definition of the symbol. 

## You are given the file name and exact symbol name.
1. Use ``get_symbol`` to get the code definition of the symbol. 

## You are NOT given the file name or exact symbol name. 
1. Investigate the codebase using ``get_project_overview`` and keywords. 
2. Use ``get_file_overview`` to get a summary of the symbols in the file.
3. Use ``get_symbol`` to get the code definition of the symbol.

## How to investigate the codebase using keywords

### ``glob``
 - Use when the clue is a path or a file name.
 - DO NOT glob for specific directory files; use ``get_directory_tree`` with the path.

### ``grep``
 - Use when the clue is specific text in file contents.
 - DO NOT grep to find which files depend on a module; use ``find_importers``.
 - DO NOT grep for reference sites of an exact symbol; use ``get_symbol_references``.

### ``search_symbols``
 - Use when the clue is part of a symbol name, signature, or docstring.
 - Set the limit to 5 if you know the local symbol name, but need the qualified name.
"""


def skill_frontmatter() -> str:
    """YAML frontmatter agents can parse.

    ``DESCRIPTION`` contains ``: ``, which is illegal in an unquoted YAML
    scalar. Cursor, Claude, Codex, Gemini, Goose, Copilot, VS Code, and
    OpenCode all read this block from ``SKILL.md`` and drop the skill
    description when the block does not parse.
    """
    dumped = yaml.safe_dump(
        {"name": "codeparse", "description": DESCRIPTION},
        sort_keys=False,
        allow_unicode=True,
    ).rstrip("\n")
    return f"---\n{dumped}\n---\n\n"


SKILL_INSTRUCTIONS = skill_frontmatter() + _SKILL_BODY


def skill_manifest(skill_bytes: bytes) -> str:
    """Skill listing served at ``skill://codeparse/_manifest``."""
    return json.dumps(
        {
            "skill": "codeparse",
            "description": DESCRIPTION,
            "files": [
                {
                    "path": "SKILL.md",
                    "size": len(skill_bytes),
                    "hash": f"sha256:{hashlib.sha256(skill_bytes).hexdigest()}",
                }
            ],
        },
        indent=2,
    )


def materialize_skill(base: Path) -> Path:
    """Write ``SKILL.md`` directly into ``base`` (the codeparse config directory)."""
    base.mkdir(parents=True, exist_ok=True)
    path = base / "SKILL.md"
    path.write_text(SKILL_INSTRUCTIONS, encoding="utf-8")
    return path


def available_skill_dirs() -> list[Path]:
    """Skill directories FastMCP already knows about that exist on disk."""
    from fastmcp.server.providers.skills import (
        ClaudeSkillsProvider,
        CodexSkillsProvider,
        CopilotSkillsProvider,
        CursorSkillsProvider,
        GeminiSkillsProvider,
        GooseSkillsProvider,
        OpenCodeSkillsProvider,
        VSCodeSkillsProvider,
    )

    providers = (
        ClaudeSkillsProvider,
        CodexSkillsProvider,
        CopilotSkillsProvider,
        CursorSkillsProvider,
        GeminiSkillsProvider,
        GooseSkillsProvider,
        OpenCodeSkillsProvider,
        VSCodeSkillsProvider,
    )
    found: list[Path] = []
    seen: set[Path] = set()
    for provider_cls in providers:
        for path in provider_cls()._roots:
            if not path.is_dir():
                continue
            if path in seen:
                continue
            seen.add(path)
            found.append(path)
    return found


def sync_skill() -> list[Path]:
    """Write the codeparse skill into FastMCP vendor skill directories that exist."""
    written: list[Path] = []
    for target in available_skill_dirs():
        skill_dir = target / "codeparse"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(SKILL_INSTRUCTIONS, encoding="utf-8")
        written.append(skill_dir)
    if not written:
        print("No skill directories found.")
        return written
    for path in written:
        print(f"Synced skill → {path}")
    return written


def remove_skill() -> list[Path]:
    """Delete synced ``codeparse`` skill directories."""
    import shutil

    removed: list[Path] = []
    for target in available_skill_dirs():
        skill_dir = target / "codeparse"
        if not skill_dir.is_dir():
            continue
        shutil.rmtree(skill_dir)
        removed.append(skill_dir)
    if not removed:
        print("No codeparse skill found.")
        return removed
    for path in removed:
        print(f"Removed skill → {path}")
    return removed
