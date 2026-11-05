import email.message
import io
import json
import ssl
import sys
import urllib.error
import zipfile
from pathlib import Path

import pytest

from src.cli import upgrade as upgrade_mod


def _zip(member: str, payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, payload)
    return buffer.getvalue()


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    tag: str,
    assets: list[str],
    current: str = "0.1.19",
) -> tuple[Path, list[list[str]], list[str]]:
    exe = tmp_path / "bin" / "codeparse"
    exe.parent.mkdir()
    exe.write_bytes(b"old")
    monkeypatch.setattr(sys, "argv", [str(exe), "update"])
    monkeypatch.setattr(upgrade_mod, "is_compiled", lambda: True)
    monkeypatch.setattr(upgrade_mod, "get_version", lambda: current)
    monkeypatch.setattr(upgrade_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(upgrade_mod.platform, "machine", lambda: "arm64")
    release = {
        "tag_name": tag,
        "assets": [{"name": name, "browser_download_url": f"https://dl/{name}"} for name in assets],
    }
    urls: list[str] = []

    def fake_get(url: str) -> bytes:
        urls.append(url)
        if url == upgrade_mod.LATEST_RELEASE_URL:
            return json.dumps(release).encode()
        tag_url = upgrade_mod.RELEASE_TAG_URL.format(tag=tag)
        if url == tag_url:
            return json.dumps(release).encode()
        if url.startswith(f"https://api.github.com/repos/{upgrade_mod.REPO}/releases/tags/"):
            raise urllib.error.HTTPError(url, 404, "Not Found", email.message.Message(), None)
        return _zip("codeparse", b"new")

    monkeypatch.setattr(upgrade_mod, "_get", fake_get)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        upgrade_mod.subprocess, "run", lambda command, **_kwargs: commands.append(command)
    )
    return exe, commands, urls


def test_upgrade_replaces_binary_and_syncs_skill(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exe, commands, urls = _setup(
        monkeypatch, tmp_path, tag="v0.2.0", assets=["codeparse-macos-arm64.zip"]
    )
    (exe.parent / "codeparse.old").write_bytes(b"stale")

    assert upgrade_mod.upgrade() == 0
    assert exe.read_bytes() == b"new"
    assert exe.stat().st_mode & 0o111
    assert not (exe.parent / "codeparse.old").exists()
    assert not (exe.parent / "codeparse.new").exists()
    assert commands == [[str(exe.resolve()), "sync"]]
    assert "Updating codeparse 0.1.19 -> 0.2.0" in capsys.readouterr().out
    assert urls[0] == upgrade_mod.LATEST_RELEASE_URL
    assert upgrade_mod.REPO == "cmgoffena13/codeparse"


def test_upgrade_minor_reloads_each_linked_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.db import CodeDB

    exe, commands, _ = _setup(
        monkeypatch, tmp_path, tag="v0.2.0", assets=["codeparse-macos-arm64.zip"]
    )
    workspace = tmp_path / "proj"
    workspace.mkdir()
    CodeDB(workspace).close()

    assert upgrade_mod.upgrade() == 0
    assert commands == [
        [str(exe.resolve()), "sync"],
        [str(exe.resolve()), "reload", "--cwd", str(workspace.resolve())],
    ]


def test_upgrade_minor_removes_index_when_workspace_is_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.db import CodeDB

    exe, commands, _ = _setup(
        monkeypatch, tmp_path, tag="v0.2.0", assets=["codeparse-macos-arm64.zip"]
    )
    workspace = tmp_path / "proj"
    workspace.mkdir()
    db = CodeDB(workspace)
    db_file = db.db_file
    db.close()
    workspace.rmdir()

    assert upgrade_mod.upgrade() == 0
    assert commands == [[str(exe.resolve()), "sync"]]
    assert not db_file.exists()


def test_upgrade_patch_does_not_reload_indexes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.db import CodeDB

    exe, commands, _ = _setup(
        monkeypatch, tmp_path, tag="v0.1.20", assets=["codeparse-macos-arm64.zip"]
    )
    workspace = tmp_path / "proj"
    workspace.mkdir()
    CodeDB(workspace).close()

    assert upgrade_mod.upgrade() == 0
    assert commands == [[str(exe.resolve()), "sync"]]


def test_upgrade_up_to_date_compares_without_v_prefix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exe, commands, _ = _setup(monkeypatch, tmp_path, tag="v0.1.19", assets=[])
    assert upgrade_mod.upgrade() == 0
    assert exe.read_bytes() == b"old"
    assert commands == []
    assert "up to date (0.1.19)" in capsys.readouterr().out


def test_upgrade_latest_never_downgrades(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe, _, _ = _setup(monkeypatch, tmp_path, tag="v0.1.9", assets=["codeparse-macos-arm64.zip"])
    assert upgrade_mod.upgrade() == 0
    assert exe.read_bytes() == b"old"


def test_upgrade_pinned_downgrades(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exe, commands, urls = _setup(
        monkeypatch,
        tmp_path,
        tag="v0.1.9",
        assets=["codeparse-macos-arm64.zip"],
        current="0.1.19",
    )
    assert upgrade_mod.upgrade(version="0.1.9") == 0
    assert exe.read_bytes() == b"new"
    assert commands == [[str(exe.resolve()), "sync"]]
    assert "Updating codeparse 0.1.19 -> 0.1.9" in capsys.readouterr().out
    assert urls[0] == upgrade_mod.RELEASE_TAG_URL.format(tag="v0.1.9")


def test_upgrade_pinned_upgrades(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exe, _, urls = _setup(monkeypatch, tmp_path, tag="v0.2.0", assets=["codeparse-macos-arm64.zip"])
    assert upgrade_mod.upgrade(version="v0.2.0") == 0
    assert exe.read_bytes() == b"new"
    assert "Updating codeparse 0.1.19 -> 0.2.0" in capsys.readouterr().out
    assert urls[0] == upgrade_mod.RELEASE_TAG_URL.format(tag="v0.2.0")


def test_upgrade_pinned_equal_is_noop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exe, commands, _ = _setup(
        monkeypatch, tmp_path, tag="v0.1.19", assets=["codeparse-macos-arm64.zip"]
    )
    assert upgrade_mod.upgrade(version="0.1.19") == 0
    assert exe.read_bytes() == b"old"
    assert commands == []
    assert "up to date (0.1.19)" in capsys.readouterr().out


def test_upgrade_pinned_missing_tag_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exe, _, _ = _setup(monkeypatch, tmp_path, tag="v0.2.0", assets=["codeparse-macos-arm64.zip"])
    assert upgrade_mod.upgrade(version="9.9.9") == 1
    assert exe.read_bytes() == b"old"
    assert "v9.9.9" in capsys.readouterr().err


def test_upgrade_missing_asset_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exe, _, _ = _setup(monkeypatch, tmp_path, tag="v0.2.0", assets=["codeparse-linux-x86_64.zip"])
    assert upgrade_mod.upgrade() == 1
    assert exe.read_bytes() == b"old"
    assert "codeparse-macos-arm64.zip" in capsys.readouterr().err


def test_upgrade_from_source_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(upgrade_mod, "is_compiled", lambda: False)
    assert upgrade_mod.upgrade() == 1
    assert "running from source" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Linux", "x86_64", "codeparse-linux-x86_64.zip"),
        ("Darwin", "arm64", "codeparse-macos-arm64.zip"),
        ("Windows", "AMD64", "codeparse-windows-x86_64.zip"),
    ],
)
def test_asset_name_matches_release_workflow(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str, expected: str
) -> None:
    monkeypatch.setattr(upgrade_mod.platform, "system", lambda: system)
    monkeypatch.setattr(upgrade_mod.platform, "machine", lambda: machine)
    assert upgrade_mod.asset_name() == expected


def test_upgrade_restores_old_binary_when_swap_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe, commands, _ = _setup(
        monkeypatch, tmp_path, tag="v0.2.0", assets=["codeparse-macos-arm64.zip"]
    )
    real_replace = Path.replace

    def flaky_replace(self: Path, target: Path) -> Path:
        if self.name == "codeparse.new":
            raise PermissionError("locked")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    with pytest.raises(PermissionError):
        upgrade_mod.upgrade()
    assert exe.read_bytes() == b"old"
    assert commands == []


def test_get_refuses_non_https() -> None:
    with pytest.raises(ValueError, match="non-HTTPS"):
        upgrade_mod._get("file:///etc/passwd")


def test_get_reads_response(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_context(*, cafile: str) -> ssl.SSLContext:
        seen["cafile"] = cafile
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def fake_urlopen(request: object, timeout: int, context: ssl.SSLContext) -> io.BytesIO:
        seen["url"] = getattr(request, "full_url", "")
        seen["context"] = context
        assert timeout == 60
        return io.BytesIO(b"payload")

    monkeypatch.setattr(upgrade_mod.ssl, "create_default_context", fake_context)
    monkeypatch.setattr(upgrade_mod.urllib.request, "urlopen", fake_urlopen)
    assert upgrade_mod._get("https://example.com/x") == b"payload"
    assert seen["url"] == "https://example.com/x"
    assert seen["cafile"] == upgrade_mod.certifi.where()
    assert seen["context"] is not None


def test_cli_upgrade_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app import main

    monkeypatch.setattr(sys, "argv", ["codeparse", "update"])
    monkeypatch.setattr(upgrade_mod, "upgrade", lambda **_kwargs: 7)
    assert main() == 7


def test_cli_upgrade_dispatches_version(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app import main

    seen: dict[str, str | None] = {}

    def capture(version: str | None = None) -> int:
        seen["version"] = version
        return 0

    monkeypatch.setattr(sys, "argv", ["codeparse", "update", "--version", "0.11.0"])
    monkeypatch.setattr(upgrade_mod, "upgrade", capture)
    assert main() == 0
    assert seen == {"version": "0.11.0"}


def test_asset_name_unknown_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_mod.platform, "system", lambda: "FreeBSD")
    monkeypatch.setattr(upgrade_mod.platform, "machine", lambda: "riscv64")
    with pytest.raises(RuntimeError, match="No codeparse build"):
        upgrade_mod.asset_name()
