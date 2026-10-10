import io
import json
import sys
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
) -> tuple[Path, list[list[str]]]:
    exe = tmp_path / "bin" / "codeparse"
    exe.parent.mkdir()
    exe.write_bytes(b"old")
    monkeypatch.setattr(sys, "argv", [str(exe), "upgrade"])
    monkeypatch.setattr(upgrade_mod, "is_compiled", lambda: True)
    monkeypatch.setattr(upgrade_mod, "get_version", lambda: "0.1.19")
    monkeypatch.setattr(upgrade_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(upgrade_mod.platform, "machine", lambda: "arm64")
    release = {
        "tag_name": tag,
        "assets": [{"name": name, "browser_download_url": f"https://dl/{name}"} for name in assets],
    }

    def fake_get(url: str) -> bytes:
        if url == upgrade_mod.LATEST_RELEASE_URL:
            return json.dumps(release).encode()
        return _zip("codeparse", b"new")

    monkeypatch.setattr(upgrade_mod, "_get", fake_get)
    synced: list[list[str]] = []
    monkeypatch.setattr(
        upgrade_mod.subprocess, "run", lambda command, **_kwargs: synced.append(command)
    )
    return exe, synced


def test_upgrade_replaces_binary_and_syncs_skill(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exe, synced = _setup(monkeypatch, tmp_path, tag="v0.2.0", assets=["codeparse-macos-arm64.zip"])
    (exe.parent / "codeparse.old").write_bytes(b"stale")

    assert upgrade_mod.upgrade() == 0
    assert exe.read_bytes() == b"new"
    assert exe.stat().st_mode & 0o111
    assert not (exe.parent / "codeparse.old").exists()
    assert not (exe.parent / "codeparse.new").exists()
    assert synced == [[str(exe.resolve()), "sync"]]
    assert "Upgrading codeparse 0.1.19 -> 0.2.0" in capsys.readouterr().out


def test_upgrade_up_to_date_compares_without_v_prefix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exe, synced = _setup(monkeypatch, tmp_path, tag="v0.1.19", assets=[])
    assert upgrade_mod.upgrade() == 0
    assert exe.read_bytes() == b"old"
    assert synced == []
    assert "up to date (0.1.19)" in capsys.readouterr().out


def test_upgrade_never_downgrades(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe, _ = _setup(monkeypatch, tmp_path, tag="v0.1.9", assets=["codeparse-macos-arm64.zip"])
    assert upgrade_mod.upgrade() == 0
    assert exe.read_bytes() == b"old"


def test_upgrade_missing_asset_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exe, _ = _setup(monkeypatch, tmp_path, tag="v0.2.0", assets=["codeparse-linux-x86_64.zip"])
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
    exe, synced = _setup(monkeypatch, tmp_path, tag="v0.2.0", assets=["codeparse-macos-arm64.zip"])
    real_replace = Path.replace

    def flaky_replace(self: Path, target: Path) -> Path:
        if self.name == "codeparse.new":
            raise PermissionError("locked")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    with pytest.raises(PermissionError):
        upgrade_mod.upgrade()
    assert exe.read_bytes() == b"old"
    assert synced == []


def test_get_refuses_non_https() -> None:
    with pytest.raises(ValueError, match="non-HTTPS"):
        upgrade_mod._get("file:///etc/passwd")


def test_get_reads_response(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_urlopen(request: object, timeout: int) -> io.BytesIO:
        seen.append(getattr(request, "full_url", ""))
        assert timeout == 60
        return io.BytesIO(b"payload")

    monkeypatch.setattr(upgrade_mod.urllib.request, "urlopen", fake_urlopen)
    assert upgrade_mod._get("https://example.com/x") == b"payload"
    assert seen == ["https://example.com/x"]


def test_cli_upgrade_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app import main

    monkeypatch.setattr(sys, "argv", ["codeparse", "upgrade"])
    monkeypatch.setattr(upgrade_mod, "upgrade", lambda: 7)
    assert main() == 7


def test_asset_name_unknown_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_mod.platform, "system", lambda: "FreeBSD")
    monkeypatch.setattr(upgrade_mod.platform, "machine", lambda: "riscv64")
    with pytest.raises(RuntimeError, match="No codeparse build"):
        upgrade_mod.asset_name()
