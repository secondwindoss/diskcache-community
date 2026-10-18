"""Classes that the tests allow through a module prefix.

The module imports ``os`` and the class Foreign from a sibling module, so
the tests can check that a pickle cannot reach either through this module.
"""

import collections
import dataclasses
import enum
import os  # noqa: F401

from tests.safedisk_models.other import Foreign  # noqa: F401


@dataclasses.dataclass
class Point:
    x: int
    y: int


@dataclasses.dataclass
class Shape:
    name: str
    points: list


class Color(enum.Enum):
    RED = 1
    GREEN = 2


class Outer:
    class Inner:
        def __init__(self, value):
            self.value = value

        def __eq__(self, other):
            return type(other) is type(self) and other.value == self.value


Pair = collections.namedtuple('Pair', 'left right')


class PointSubclass(Point):
    pass
