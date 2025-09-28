"""
Test module for proxying
"""

from __future__ import annotations

from moat.util import as_proxy

# ruff: noqa: D101, D103


class Bar:
    def __init__(self, x):
        self.x = x

    def __repr__(self):
        return f"{self.__class__.__name__}.x={self.x}"


@as_proxy("fu")
class Foo(Bar):
    pass


b = as_proxy("b", Bar(95))


async def run():
    pass
