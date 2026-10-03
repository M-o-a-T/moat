"""
Test module for proxying
"""

from __future__ import annotations

from moat.lib.proxy import as_proxy

# ruff: noqa: D101, D103


class Bar:
    def __init__(self, x) -> None:
        self.x = x

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.x={self.x}"


@as_proxy("fu")
class Foo(Bar):
    pass


b = as_proxy("b", Bar(95))


async def run() -> None:
    pass
