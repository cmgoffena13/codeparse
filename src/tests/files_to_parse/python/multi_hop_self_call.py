class Engine:
    def execute(self) -> None:
        pass


class Context:
    engine: Engine

    def plan(self) -> None:
        pass


class HostClass:
    def __init__(self, context: Context) -> None:
        self.context = context

    def run(self) -> None:
        self.context.engine.execute()
