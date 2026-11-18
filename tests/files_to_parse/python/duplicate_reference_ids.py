def callee() -> int:
    return 1


def caller() -> int:
    x = callee()
    y = callee()
    return x + y
