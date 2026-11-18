import pkgutil


def f(obj):
    pkgutil.walk_packages()
    obj.a.b
    obj.m().n
