class Engine:
    def execute(self) -> None:
        pass


class HostClass:
    engine: Engine

    def run(self) -> None:
        self.engine.execute()
