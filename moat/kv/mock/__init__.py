# from asyncclick.testing import CliRunner
from __future__ import annotations
import logging
import socket

import attr
from asyncscope import scope
from moat.util import (  # pylint:disable=no-name-in-module
    CFG,
    combine_dict,
    ensure_cfg,
)

from moat.kv.client import _scoped_client

logger = logging.getLogger(__name__)
try:
    from contextlib import asynccontextmanager
except ImportError:
    from async_generator import asynccontextmanager

ensure_cfg("moat.kv")


@attr.s
class S:
    tg = attr.ib()
    client_ctx = attr.ib()
    s = attr.ib(factory=list)  # servers
    c = attr.ib(factory=list)  # clients
    _seq = 1

    async def ready(self, i=None):
        if i is not None:
            await self.s[i].is_ready
            return self.s[i]
        for s in self.s:
            if s is not None:
                await s.is_ready
        return self.s

    def __iter__(self):
        return iter(self.s)

    @asynccontextmanager
    async def client(self, i: int = 0, **kv):
        """Get a (new) client for the i'th server."""
        await self.s[i].is_serving
        self._seq += 1
        for host, port, *_ in self.s[i].ports:
            if host != "::" and host[0] == ":":
                continue
            try:
                cfg = combine_dict(
                    dict(conn=dict(host=host, port=port, ssl=self.client_ctx, **kv)),
                    CFG["kv"],
                )

                async def scc(s, **cfg):
                    scope.requires(s._scope)
                    return await _scoped_client(scope.name, **cfg)

                async with scope.using_scope():
                    c = await scope.service(
                        f"moat.kv.client.{i}.{self._seq}",
                        scc,
                        self.s[i],
                        **cfg,
                    )
                    yield c
                return
            except socket.gaierror:
                pass
        raise RuntimeError("Duh? no connection")

    async def run(self, *args, do_stdout=True):
        from moat.src.test import run as run_  # pylint:disable=import-error,no-name-in-module
        h = p = None
        for s in self.s:
            for h, p, *_ in s.ports:
                if h[0] != ":":
                    break
            else:
                continue
            break
        if len(args) == 1:
            args = args[0]
            if isinstance(args, str):
                args = args.split(" ")
        async with scope.using_scope():
            return await run_("-VV", "kv", "-h", h, "-p", p, *args, do_stdout=do_stdout)
