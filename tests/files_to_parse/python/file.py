# Regular Import
import json

# Symbol Import
from pathlib import Path

# Relative Import + Alias Import
from .another_file import variable_in_another_file as alias_variable_in_another_file

alias_variable_in_another_file = "test"

# Variable Assignment
fake_path = Path(".").resolve()

# Variable Assignment
data = json.dumps(
    {
        "fake_data": "test",
    },
    indent=4,
)


def _noop_deco(fn):
    return fn


# Class check
class FakeClass:
    """
    Fake Class Milti Line Docstring

    This is a fake class with a multi line docstring.
    """

    def __init__(self):
        self.fake_data = "test"

    # Decorator
    @_noop_deco
    @property
    def fake_property(self):
        return self.fake_data

    # Class Method
    def fake_method(self):
        return self.fake_data


# Function Check
def fake_function():
    """Fake Function Docstring"""

    # Nested Function Check
    def nested_fake_function():
        return "nested_fake_function"

    return nested_fake_function()


# Multiline Signature Check
def multiline_signature(
    a: int,
    b: int,
    c: int,
    d: int,
    e: int,
    f: int,
    g: int,
    h: int,
    i: int,
    j: int,
) -> int:
    return a + b + c + d + e + f + g + h + i + j
