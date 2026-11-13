from pathlib import Path

import xxhash
import yaml

DESCRIPTION = (
    "Use when navigating a Python codebase: symbol definitions, "
    "module/symbol dependencies. Includes external modules/symbols "
    "(stdlib and third-party names work with the tools)."
)

_SKILL_BODY = """\
# IMPORTANT RULES
 - ALWAYS use codeparse tools to get symbol definitions.
 - NEVER use ``read`` on a Python file.
 - Only ``include_tests`` when making changes to the codebase. 
 - DO NOT ``include_tests`` when investigating unless explicitly asked.

# INSTRUCTIONS

The information that is provided to you will determine the tool you should use.

## You are given the file name.
1. Use ``get_file_symbol_tree`` to get a file's nested symbol tree.
2. Use ``get_symbol`` to get the symbol definition.

## You are given the file name and symbol's qualified name.
1. Use ``get_symbol`` to get the symbol definition. 

## You are given a file name and line numbers from ``grep`` or a ``code selection`` in Cursor.
1. Use ``get_symbol_at_lines`` to get the symbol definition that covers those lines.

## You are NOT given the file name or symbol's qualified name. 
1. Investigate the codebase using ``get_entry_points`` and keywords. 
2. Use ``get_file_symbol_tree`` to get a file's nested symbol tree.
3. Use ``get_symbol`` to get the symbol definition. 

### Investigate the codebase using keywords

#### ``glob``
 - Use when the clue is a path or a file name.

#### ``grep``
 - Use when the clue is specific text in file contents.
 - Use `-n` to get the line number and then use ``get_symbol_at_lines`` to get the symbol.
 - Use ``get_import_relations`` for module dependents or dependencies; DO NOT grep for this.
 - Use ``get_symbol_relations`` for symbol dependents or dependencies; DO NOT grep for this.
 - Use ``get_class_tree`` for a class inheritance tree; DO NOT grep for this.

#### ``search_symbols``
 - Use when the clue is a reference to a symbol name.
 - Set the limit to 5 if you know the local symbol name, but need the qualified name.

# RESOURCES

## ``stats://codeparse/sessions``
 - Only use when the question is about codeparse sessions, cost, or decision quality.
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


def _vendor_skill_roots() -> list[Path]:
    home = Path.home()
    return [
        home / ".claude" / "skills",
        Path("/etc/codex/skills"),
        home / ".codex" / "skills",
        home / ".copilot" / "skills",
        home / ".cursor" / "skills",
        home / ".gemini" / "skills",
        home / ".config" / "agents" / "skills",
        home / ".config" / "opencode" / "skills",
    ]


def available_skill_dirs() -> list[Path]:
    """Skill directories FastMCP vendor clients use that exist on disk."""
    found: list[Path] = []
    seen: set[Path] = set()
    for path in _vendor_skill_roots():
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
