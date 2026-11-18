class DependencyType:
    def invoke(self) -> None:
        pass


class HostClass:
    def __init__(self, dep: DependencyType) -> None:
        self.dep = dep

    def run(self) -> None:
        self.dep.invoke()
        _ = self.dep
