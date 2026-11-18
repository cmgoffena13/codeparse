from pkg.base import Parent


class TestChild(Parent):
    pass


def test_parent() -> Parent:
    return Parent()
