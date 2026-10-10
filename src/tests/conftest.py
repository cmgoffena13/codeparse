import sys
from collections.abc import Callable
from pathlib import Path

import pytest

# Ensure repository root is importable (so `import src.*` works)
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

collect_ignore = ["test_project"]

from src.assigner import GlobalIDAssigner
from src.db import CodeDB
from src.parsers.factory import ParserFactory


@pytest.fixture(autouse=True)
def _isolate_code_parse_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep index DBs under this test's tmp dir (see ``utils.get_code_parse_config_dir``)."""
    monkeypatch.setenv(
        "CODE_PARSE_CONFIG_DIR",
        str(tmp_path / "codeparse-config"),
    )


@pytest.fixture
def mcp_client(_isolate_code_parse_config: None):
    """In-process FastMCP client for the codeparse server."""
    from fastmcp import Client

    from src.codeparse_mcp import server
    from src.codeparse_mcp.skill import materialize_skill
    from src.utils import get_code_parse_config_dir

    # A previous test in this process may have imported the server first.
    server._SKILL_PATH = materialize_skill(get_code_parse_config_dir())
    return Client(server.mcp)


@pytest.fixture
def tmp_db(tmp_path: Path) -> CodeDB:
    return CodeDB(tmp_path)


@pytest.fixture
def assigner(tmp_db: CodeDB) -> GlobalIDAssigner:
    return GlobalIDAssigner(tmp_db)


@pytest.fixture
def python_parser(tmp_db: CodeDB, assigner: GlobalIDAssigner):
    return ParserFactory.get_parser("python", assigner, tmp_db)


@pytest.fixture
def python_fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "files_to_parse" / "python"


@pytest.fixture
def fixture_bytes(python_fixtures_dir: Path) -> Callable[[str], bytes]:
    def _read(name: str) -> bytes:
        return (python_fixtures_dir / name).read_bytes()

    return _read
