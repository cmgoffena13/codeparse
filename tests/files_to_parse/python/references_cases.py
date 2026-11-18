from pathlib import Path


def takes_path(p: Path) -> None:
    pass


class RefClass:
    def __init__(self):
        self.value = 2

    def method(self, p: Path) -> int:
        x: int = 1
        # access reference
        return x + self.value


ref = RefClass()
takes_path(Path("."))
