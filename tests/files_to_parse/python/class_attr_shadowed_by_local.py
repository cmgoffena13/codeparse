from dataclasses import dataclass, field


@dataclass
class HarnessResults:
    results: list = field(default_factory=list)


class Harness:
    def run(self) -> HarnessResults:
        results = HarnessResults()
        results.results.append(1)
        return results
