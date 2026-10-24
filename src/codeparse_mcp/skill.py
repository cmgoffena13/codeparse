from pathlib import Path

import xxhash
import yaml

DESCRIPTION = (
    "Use when navigating a Python codebase: mapping repo structure, finding "
    "entry points, locating symbols, tracing inheritance, or understanding how files and symbols "
    "depend on each other."
)

_SKILL_BODY = """\
# IMPORTANT RULES
 - ALWAYS use codeparse tools to get symbol information.
 - NEVER use ``read`` on a Python file.
 - Only ``include_tests`` when making changes to the codebase. 
 - DO NOT ``include_tests`` when investigating unless explicitly asked.

# INSTRUCTIONS

The information that is provided to you will determine the tool you should use.

## You are given the file name.
1. Use ``get_file_symbols`` to get a file's nested symbol tree.
2. Use ``get_symbol`` to get the symbol definition.

## You are given the file name and symbol's qualified name.
1. Use ``get_symbol`` to get the symbol definition. 

## You are given a file name and line numbers from ``grep`` or a ``code selection`` in Cursor.
1. Use ``get_symbol_at_lines`` to get the symbol definition that covers those lines.

## You are NOT given the file name or symbol's qualified name. 
1. Investigate the codebase using ``get_project_overview`` and keywords. 
2. Use ``get_file_symbols`` to get a file's nested symbol tree.
3. Use ``get_symbol`` to get the symbol definition. 

### How to investigate the codebase using keywords

#### ``glob``
 - Use when the clue is a path or a file name.

#### ``grep``
 - Use when the clue is specific text in file contents.
 - Use `-n` to get the line number and then use ``get_symbol_at_lines`` to get the symbol.
 - Use ``list_importers`` to find which files depend on a module; DO NOT grep for this.
 - Use ``get_file_imports`` to list a file's import statements; DO NOT grep for this.
 - Use ``get_symbol_references`` to find reference sites of an exact symbol; DO NOT grep for this.
 - Use ``list_subclasses`` to find subclasses of a class; DO NOT grep for this.

#### ``search_symbols``
 - Use when the clue is a reference to a symbol name.
 - Set the limit to 5 if you know the local symbol name, but need the qualified name.

# Resources

## ``stats://codeparse/sessions``
 - Only use when the question is about codeparse cost or decision quality.
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
    targets = available_skill_dirs()
    if not targets:
        print("No skill directories found.")
    else:
        skill_bytes = SKILL_INSTRUCTIONS.encode("utf-8")
        current_hash = xxhash.xxh128(skill_bytes).hexdigest()
        for target in targets:
            skill_dir = target / "codeparse"
            skill_path = skill_dir / "SKILL.md"
            existing = skill_path.read_bytes() if skill_path.is_file() else b""
            if xxhash.xxh128(existing).hexdigest() == current_hash:
                continue
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_path.write_bytes(skill_bytes)
            written.append(skill_dir)
        if written:
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
