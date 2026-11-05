"""Replace the codeparse binary with a GitHub release."""

import contextlib
import io
import json
import platform
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

import certifi

from src.utils import binary_path, get_version, is_compiled

REPO = "cmgoffena13/codeparse"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_TAG_URL = f"https://api.github.com/repos/{REPO}/releases/tags/{{tag}}"

_SYSTEMS = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}
_ARCHES = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}


def _get(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"Refusing non-HTTPS download: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "codeparse"})  # noqa: S310
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=60, context=context) as response:  # noqa: S310
        return response.read()


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.removeprefix("v").split("."))


def _minor_changed(current: str, tag: str) -> bool:
    """True when major or minor differs. A patch bump does not rebuild indexes."""

    def pair(version: str) -> tuple[int, int]:
        parts = _version_key(version)
        major = parts[0] if parts else 0
        minor = parts[1] if len(parts) > 1 else 0
        return major, minor

    return pair(current) != pair(tag)


def asset_name() -> str:
    """Release zip for this platform, matching ``build-release.yml``."""
    system = _SYSTEMS.get(platform.system())
    arch = _ARCHES.get(platform.machine().lower())
    if system is None or arch is None:
        raise RuntimeError(f"No codeparse build for {platform.system()} {platform.machine()}")
    return f"codeparse-{system}-{arch}.zip"


def upgrade(version: str | None = None) -> int:
    result = 1
    if not is_compiled():
        print("codeparse is running from source; update with git instead.", file=sys.stderr)
    else:
        exe = binary_path()
        old = exe.with_name(exe.name + ".old")
        with contextlib.suppress(OSError):
            old.unlink(missing_ok=True)

        current = get_version()
        release = None
        tag = ""
        try:
            if version is None:
                release = json.loads(_get(LATEST_RELEASE_URL))
            else:
                tag = f"v{version.removeprefix('v')}"
                release = json.loads(_get(RELEASE_TAG_URL.format(tag=tag)))
        except urllib.error.HTTPError:
            label = tag if tag else "latest"
            print(f"No GitHub release found for {label}", file=sys.stderr)
        if release is not None:
            tag = release["tag_name"]
            target_key = _version_key(tag)
            current_key = _version_key(current)
            skip = target_key == current_key or (version is None and target_key <= current_key)
            if skip:
                print(f"codeparse is up to date ({current})")
                result = 0
            else:
                name = asset_name()
                asset = next((a for a in release["assets"] if a["name"] == name), None)
                if asset is None:
                    print(f"No release asset named {name} in {tag}", file=sys.stderr)
                else:
                    print(f"Updating codeparse {current} -> {tag.removeprefix('v')}...")
                    member = "codeparse.exe" if platform.system() == "Windows" else "codeparse"
                    payload = _get(asset["browser_download_url"])
                    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
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

                    print(f"Updated codeparse to {tag.removeprefix('v')}")
                    subprocess.run([str(exe), "sync"], check=False)  # noqa: S603
                    if _minor_changed(current, tag):
                        from src.db import index_workspace_paths

                        for db_file, root in index_workspace_paths():
                            if not root.is_dir():
                                print(f"Removing index for missing workspace {root}")
                                db_file.unlink(missing_ok=True)
                                db_file.with_suffix(".db-wal").unlink(missing_ok=True)
                                db_file.with_suffix(".db-shm").unlink(missing_ok=True)
                                continue
                            print(f"Reloading index for {root}")
                            subprocess.run(  # noqa: S603
                                [str(exe), "reload", "--cwd", str(root)], check=False
                            )
                    result = 0
    return result
