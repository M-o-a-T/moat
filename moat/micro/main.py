"""
Code to set up a link to a MicroPython client device
"""
from __future__ import annotations

import hashlib
import io
import logging
from contextlib import asynccontextmanager
from itertools import chain
from pathlib import Path

import anyio
from anyio_serial import Serial
from moat.util import NotGiven, attrdict

from moat.micro.cmd.base import BaseCmd
from moat.micro.compat import Event, TaskGroup
from moat.micro.stacks.console import console_stack
from moat.micro.proto.stream import AnyioBuf

logger = logging.getLogger(__name__)


class ClientBaseCmd(BaseCmd):
    """
    a BaseCmd subclass that adds link state tracking
    """

    def __init__(self, parent, *, cfg=None):
        super().__init__(parent)
        self.cfg = cfg
        self.started = Event()

    def cmd_link(self, s=None):  # pylint: disable=unused-argument
        """Link-up command handler, sets `started`"""
        self.started.set()

    async def wait_start(self):
        """Wait until a "link" command arrives"""
        await self.started.wait()


class NoPort(RuntimeError):
    "Config error: no port given"
    pass  # pylint:disable=unnecessary-pass


class CfgStore:
    """
    Config file storage.
    """

    def __init__(self, root:Dispatch, path=(), sub=(), cfg=None):
        self.root = root
        self.path = tree
        self.cfg = cfg
        self.subpath = ()

    async def get_cfg(self, again=False):
        """
        Collect the client's configuration data.
        """

        async def _get_cfg(p):
            d = await self.send("r", p=p)
            if isinstance(d, (list, tuple)):
                d, s = d
                if isinstance(d, dict):
                    d = attrdict(d)
                for k in s:
                    d[k] = await _get_cfg(p + (k,))
            return d

        if self.cfg and not again:
            return self.cfg
        cfg = await _get_cfg(self.subpath)
        self.cfg = cfg
        return cfg

    async def set_cfg(self, cfg, replace=False, sync=False):
        """
        Update the client's configuration data.

        If @replace is set, the config file is complete and any other items
        will be deleted from the client.

        If @sync is set, the client will reload apps etc. after updating
        the config.
        """

        async def _set_cfg(p, c):
            # current client cfg
            try:
                ocd, ocl = await self.send("w", p=p)
            except KeyError:
                ocd = {}
                ocl = []
                await self.send("w", p=p, d={})
            for k, v in c.items():
                if isinstance(v, dict):
                    await _set_cfg(p + (k,), v)
                elif ocd.get(k, NotGiven) != v:
                    await self.send("w", p=p + (k,), d=v)

            if not replace:
                return
            # drop those client cfg snippets that are not on the server
            for k in chain(ocd.keys(), ocl):
                if k not in c:
                    await self.send("w", p=p + (k,), d=NotGiven)

        await _set_cfg(self.subpath, cfg)
        if sync:
            await self.send("x")  # runs

    async def send(self, sub, **kw):
        return await self.root.send(self.path+("cfg",sub), **kw)
