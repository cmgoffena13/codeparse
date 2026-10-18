ITEMS: dict[str, int] = {"a": 1}


class Box:
    def run(self) -> None:
        return ITEMS.get("a")
