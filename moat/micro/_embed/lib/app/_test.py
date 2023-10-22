"""
Apps used for testing.
"""

from __future__ import annotations

from moat.micro.cmd.base import BaseCmd
from moat.micro.compat import log

class Cmd(BaseCmd):
    n = 0
    async def cmd_echo(self, m:Any):
        return {'r':m}

    def iter_it(self, lim:int=None):
        return NumIter(lim)

    def cmd_nit(self, lim:int=None):
        self.n += 1
        log("NIT %d",self.n)
        if lim is not None and self.n > lim:
            raise StopAsyncIteration
        return self.n

class NumIter:
    def __init__(self, lim):
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
