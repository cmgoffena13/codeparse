"""Shared formatting helpers for MCP tool output."""


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
    """``name``, ``name (12L)``, or ``name (12L, 3S)``."""
    label = name or "(unknown path)"
    if line_count <= 0:
        return label
    stats = f"({line_count}L)" if symbol_count <= 0 else f"({line_count}L, {symbol_count}S)"
    return f"{label} {stats}"
