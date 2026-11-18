def callee() -> int:
    return 1


def caller() -> int:
    return callee(); callee()
