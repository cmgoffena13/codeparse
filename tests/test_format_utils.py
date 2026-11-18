from src.codeparse_mcp.format_utils import tree_glyphs


def test_tree_glyphs_narrow() -> None:
    assert tree_glyphs(False) == ("├─ ", "│  ")
    assert tree_glyphs(True) == ("└─ ", "   ")


def test_tree_glyphs_wide() -> None:
    assert tree_glyphs(False, wide=True) == ("├── ", "│   ")
    assert tree_glyphs(True, wide=True) == ("└── ", "    ")
