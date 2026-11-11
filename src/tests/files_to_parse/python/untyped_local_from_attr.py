class Context:
    def plan(self) -> None:
        pass


class HostClass:
    def __init__(self, context: Context) -> None:
        self.context = context

    def run(self) -> None:
        ctx = self.context
        ctx.plan()
