"""
Apps used for testing.
"""

from __future__ import annotations

from moat.micro.cmd.base import BaseCmd

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Any


class Cmd(BaseCmd):
    """
    A rather basic test command.
    """

    n = 0

    async def cmd_echo(self, m: Any):
        "Basic echo method, returns @m as ``result[" r"]``"
        return {'r': m}

    def iter_it(self, lim: int = None):
        "returns a `NumIter`"
        return NumIter(lim)

    def cmd_nit(self, lim: int = None):
        "A non-iterator counter; simply counts calls to it."
        self.n += 1
        if lim is not None and self.n > lim:
            raise StopAsyncIteration
        return self.n

    def cmd_clr(self, n: int = 0):
        self.n = n


class NumIter:
    """
    A test iterator that mimics ``range(0,‹lim›)``.
    """

    def __init__(self, lim=None):
        self.lim = lim
        self.n = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.lim is not None and self.n >= self.lim:
            raise StopAsyncIteration
        n = self.n
        self.n += 1
        return n
