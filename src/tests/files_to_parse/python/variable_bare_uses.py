from pkg.data import ITEMS as BOX

ITEMS: dict[str, int] = {"a": 1}


def run(index, item):
    if item in ITEMS:
        pass
    if item not in ITEMS:
        pass
    value = ITEMS[index]
    return ITEMS


def imported(item):
    if item in BOX:
        return BOX
