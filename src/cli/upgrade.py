"""Replace the codeparse binary with the latest GitHub release."""

import contextlib
import io
import json
import platform
import subprocess
import sys
import urllib.request
import zipfile

from src.utils import binary_path, get_version, is_compiled

REPO = "cmgoffena13/codebase-parse"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

_SYSTEMS = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}
_ARCHES = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}


def _get(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"Refusing non-HTTPS download: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "codeparse"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read()


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.removeprefix("v").split("."))


def asset_name() -> str:
    """Release zip for this platform, matching ``build-release.yml``."""
    system = _SYSTEMS.get(platform.system())
    arch = _ARCHES.get(platform.machine().lower())
    if system is None or arch is None:
        raise RuntimeError(f"No codeparse build for {platform.system()} {platform.machine()}")
    return f"codeparse-{system}-{arch}.zip"


def upgrade() -> int:
    if not is_compiled():
        print("codeparse is running from source; upgrade with git instead.", file=sys.stderr)
        return 1

    exe = binary_path()
    old = exe.with_name(exe.name + ".old")
    # Windows can only rename a running exe, so the previous upgrade may have left this behind.
    with contextlib.suppress(OSError):
        old.unlink(missing_ok=True)

    release = json.loads(_get(LATEST_RELEASE_URL))
    tag = release["tag_name"]
    current = get_version()
    if _version_key(tag) <= _version_key(current):
        print(f"codeparse is up to date ({current})")
        return 0

    name = asset_name()
    asset = next((a for a in release["assets"] if a["name"] == name), None)
    if asset is None:
        print(f"No release asset named {name} in {tag}", file=sys.stderr)
        return 1

    print(f"Upgrading codeparse {current} -> {tag.removeprefix('v')}...")
    member = "codeparse.exe" if platform.system() == "Windows" else "codeparse"
    with zipfile.ZipFile(io.BytesIO(_get(asset["browser_download_url"]))) as archive:
        binary = archive.read(member)

    new = exe.with_name(exe.name + ".new")
    new.write_bytes(binary)
    new.chmod(0o755)
    exe.replace(old)
    try:
        new.replace(exe)
    except OSError:
        old.replace(exe)
        raise
    with contextlib.suppress(OSError):
        old.unlink()

    print(f"Upgraded codeparse to {tag.removeprefix('v')}")
    subprocess.run([str(exe), "sync"], check=False)  # noqa: S603
    return 0
