from other.types import DependencyType


class HostClass:
    def __init__(self, dep: DependencyType) -> None:
        self.dep = dep

    def run(self) -> None:
        self.dep.invoke()
        _ = self.dep
