from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.db import CodeDB
from src.parsers.base import ParserBase
from src.parsers.parser_utils import StackFrame


def test_parser_base_stack_holds_stack_frames(tmp_path: Path) -> None:
    db = CodeDB(tmp_path)
    base = ParserBase(MagicMock(), db, MagicMock())
    frame = StackFrame(1, "pkg.mod.Foo", "class", False, "Foo")
    base.stack.append(frame)
    assert base.stack[-1] is frame
    assert base.stack[-1].qualified_name == "pkg.mod.Foo"
    db.close()


def test_parser_base_parse_not_implemented(tmp_path: Path) -> None:
    db = CodeDB(tmp_path)
    base = ParserBase(MagicMock(), db, MagicMock())
    with pytest.raises(NotImplementedError):
        base.parse(1, b"")
    db.close()
