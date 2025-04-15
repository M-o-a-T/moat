"""
Server-side dir support
"""

from __future__ import annotations
import sys

from itertools import chain

from moat.util import NotGiven, attrdict

from ._dir import Dispatch as _Dispatch  # isort:skip
from ._dir import BaseSubCmd, BaseSuperCmd, DirCmd  # noqa:F401

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.util import Path


class _NotGiven:
    pass


class Dispatch(_Dispatch):
    "Root dispatcher"

    APP = "moat.micro.app"

    def __init__(self, cfg, sig=False, **kw):
        super().__init__(cfg, **kw)
        self.sig = sig

    async def setup(self):
        "Root setup: adds signal handling if requested"
        await super().setup()
        if self.sig:

            async def sig_handler():
                import anyio
                import signal  # pylint:disable=import-outside-toplevel

                with anyio.open_signal_receiver(
                    signal.SIGINT,
                    signal.SIGTERM,
                    signal.SIGHUP,
                ) as signals:
                    async for _ in signals:
                        self.tg.cancel()
                        break  # default handler on next

            await self.tg.spawn(sig_handler, _name="sig")

    def cfg_at(self, p: Path):
        "returns a CfgStore object at this subpath"
        return CfgStore(self, p)


class CfgStore:
    """
    Config file storage.

    The subpath points to the destination's "cfg.Cmd" app.
    """

    cfg: dict = None
    subpath = ()

    def __init__(self, dispatch, path: Path):
        self.sd = dispatch.sub_at(path)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    async def get(self, again=False):
        """
        Collect the client's configuration data.
        """

        async def _get(p):
            d = await self.sd.r(p)
            if isinstance(d, dict):
                return d
            if len(d) == 2:
                d, s = d
                if isinstance(d, dict):
                    d = attrdict(d)
                for k in s:
                    d[k] = await _get(p + (k,))
            else:
                d = d[0]
            return d

        if self.cfg and not again:
            return self.cfg
        cfg = await _get(self.subpath)
        self.cfg = cfg
        return cfg

    async def set(self, cfg, replace=False, sync=False):
        """
        Update the client's configuration data.

        If @replace is set, the config file is complete and any other items
        will be deleted from the client.

        If @sync is set, the client will reload apps etc. after updating
        the config.
        """

        async def _set(p, c):
            # current client cfg
            print("SET", p, c, file=sys.stderr)
            try:
                ocd = await self.sd.r(p)
                if isinstance(ocd, (list, tuple)):
                    ocd, ocl = ocd
                else:
                    ocl = ()
            except KeyError:
                ocd = {}
                ocl = []
                await self.sd.w(p, d={})
            for k, v in c.items():
                if isinstance(v, dict):
                    await _set(p + (k,), v)
                elif ocd.get(k, _NotGiven) != v:
                    await self.sd.w(p + (k,), d=v)

            if not replace:
                return
            # drop those client cfg snippets that are not on the server
            for k in chain(ocd.keys(), ocl):
                if k not in c:
                    await self.sd.w(p + (k,), d=NotGiven)

        self.cfg = None
        await _set(self.subpath, cfg)

        if sync:
            await self.sd.x()  # runs
