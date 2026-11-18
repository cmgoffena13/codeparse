from pathlib import Path


def use_path() -> None:
    Path(".")


def use_join() -> None:
    ",".join(["a", "b"])


def use_local(files: dict) -> None:
    files.values()
