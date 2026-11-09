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


def page_window(total: int, page: int, page_size: int, *, label: str) -> tuple[int, int, int] | str:
    page_count = (total + page_size - 1) // page_size if total else 0
    result: tuple[int, int, int] | str
    if page < 1:
        result = "Invalid page; pass page >= 1."
    elif page_count == 0 or page > page_count:
        result = f"No more {label}; page {page} is past {max(page_count, 1)}."
    else:
        start = (page - 1) * page_size
        result = (start, min(start + page_size, total), page_count)
    return result


def page_footer(page: int, page_count: int, shown: int, total: int, label: str) -> str:
    return f"… page {page} of {page_count} ({shown} of {total} {label})"


def format_paged_file_entries(
    entries: list[tuple[str, str, dict[str, int]]],
    *,
    page: int,
    page_size: int,
    label: str,
) -> str:
    total = len(entries)
    window = page_window(total, page, page_size, label=label)
    result: str
    if isinstance(window, str):
        result = window
    else:
        start, stop, page_count = window
        shown = entries[start:stop]
        lines_out: list[str] = []
        previous_path: str | None = None
        for path, entry_label, kind_counts in shown:
            if path != previous_path:
                if lines_out:
                    lines_out.append("")
                lines_out.append(path)
                previous_path = path
            lines_out.append(bullet(entry_label + kind_count_suffix(kind_counts)))
        body = "\n".join(lines_out).strip() + "\n"
        result = body
        if page_count > 1:
            result = (
                body.rstrip("\n")
                + "\n\n"
                + page_footer(page, page_count, len(shown), total, label)
                + "\n"
            )
    return result
