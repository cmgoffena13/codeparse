def deco(fn):
    return fn


class Marker:
    @staticmethod
    def wrap(fn):
        return fn


@deco
def bare() -> None:
    pass


@deco(1)
def with_args() -> None:
    pass


@Marker.wrap
def dotted() -> None:
    pass


@deco
class Decorated:
    @property
    def value(self) -> int:
        return 1
