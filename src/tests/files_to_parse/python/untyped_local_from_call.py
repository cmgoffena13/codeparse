class Plan:
    def apply(self) -> None:
        pass


class Context:
    def plan(self) -> Plan:
        return Plan()


class HostClass:
    def __init__(self, context: Context) -> None:
        self.context = context

    def run(self) -> None:
        node = self.context.plan()
        node.apply()
