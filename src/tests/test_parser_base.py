from pathlib import Path
from unittest.mock import MagicMock

import pytest
import tree_sitter_python as python_language
from tree_sitter import Language, Parser

from src.db import CodeDB
from src.parsers.base import ParserBase
from src.parsers.parser_utils import StackFrame, node_text


def test_parser_base_stack_holds_stack_frames(tmp_path: Path) -> None:
    db = CodeDB(tmp_path)
    base = ParserBase(MagicMock(), db, MagicMock())
    frame = StackFrame(1, "pkg.mod.Foo", "class", False, "Foo")
    base.stack.append(frame)
    assert base.stack[-1] is frame
    assert base.stack[-1].qualified_name == "pkg.mod.Foo"
    db.close()


def test_node_text_reads_an_identifier_and_rejects_none() -> None:
    parser = Parser(Language(python_language.language()))
    root = parser.parse(b"alpha = 1\n").root_node
    found = None
    pending = [root]
    while pending:
        current = pending.pop()
        if current.type == "identifier":
            found = current
            break
        pending.extend(current.named_children)
    assert node_text(found) == "alpha"
    assert node_text(None) is None


def test_parser_base_parse_not_implemented(tmp_path: Path) -> None:
    db = CodeDB(tmp_path)
    base = ParserBase(MagicMock(), db, MagicMock())
    with pytest.raises(NotImplementedError):
        base.parse(1, b"")
    db.close()
