"""Shared formatting helpers for MCP tool output."""

_KIND_ORDER = ("call", "access")
_KIND_LETTER = {
    "call": "C",
    "access": "A",
}


def kind_count_suffix(counts: dict[str, int]) -> str:
    parts: list[str] = []
    for kind in _KIND_ORDER:
        if kind in counts:
            letter = _KIND_LETTER[kind]
            n = counts[kind]
            parts.append(f"({letter}) ({n})" if n > 1 else f"({letter})")
    for kind in sorted(k for k in counts if k not in _KIND_LETTER):
        n = counts[kind]
        letter = kind[0].upper()
        parts.append(f"({letter}) ({n})" if n > 1 else f"({letter})")
    return " " + " ".join(parts)


def line_span(line_start: int, line_end: int) -> str:
    """``L12`` or ``L12-34``."""
    if line_start == line_end:
        return f"L{line_start}"
    return f"L{line_start}-{line_end}"


def lines_range(line_start: int, line_end: int) -> str:
    """``12`` or ``12-34`` (no ``L`` prefix)."""
    if line_start == line_end:
        return str(line_start)
    return f"{line_start}-{line_end}"


def bullet(text: str, lead: str = "") -> str:
    """``  • text``. A ``lead`` such as ``#1 `` sits before the dot."""
    return f"  {lead}• {text}"


def file_label(name: str, line_count: int, symbol_count: int) -> str:
    """``name`` when the file has no lines, otherwise ``name (12L, 3S)``."""
    label = name or "(unknown path)"
    if line_count > 0:
        label = f"{label} ({line_count}L, {symbol_count}S)"
    return label


def tree_glyphs(is_last: bool, *, wide: bool = False) -> tuple[str, str]:
    narrow = (("├─ ", "│  "), ("└─ ", "   "))
    wide_glyphs = (("├── ", "│   "), ("└── ", "    "))
    return (wide_glyphs if wide else narrow)[int(is_last)]
