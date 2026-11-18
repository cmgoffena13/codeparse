class Worker:
    def process(self) -> None:
        pass


def boot() -> None:
    worker: Worker = Worker()
    worker.process()
