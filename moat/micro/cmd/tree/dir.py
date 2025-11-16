"""
Server-side dir support
"""

from __future__ import annotations

from itertools import chain

from moat.util import NotGiven, Path

from ._dir import Dispatch as _Dispatch  # isort:skip
from ._dir import BaseSubCmd, BaseSuperCmd, DirCmd  # noqa:F401

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.cmd.base import MsgSender


class _NotGiven:
    # This is distinct from the "real" NotGiven. This is intentional.
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
                import anyio  # noqa: PLC0415
                import signal  # pylint:disable=import-outside-toplevel  # noqa: PLC0415

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


class SubStore:
    """
    A helper class to retrieve a possibly-encoded object.
    """

    cfg: dict = None

    def __init__(self, sd: MsgSender):
        self.__sd = sd

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    async def get(self, *a, **kw):
        """
        Collect a parts-encoded reply.
        """
        rp = kw.pop("p", Path())

        async def _get(p):
            d = await self.__sd(*a, p=p, **kw)
            if isinstance(d, (list, tuple)) and len(d) == 2:
                d, s = d
                for k in s:
                    d[k] = await _get(p + (k,))
            return d

        return await _get(rp)


class CfgStore(SubStore):
    """
    Config file storage.

    The subpath points to the destination's "cfg.Cmd" app, or a
    similar class that exposes ``r``, ``w`` and possibly ``x`` commands.
    """

    def __init__(self, dispatch, path: Path):
        self.sd = dispatch.sub_at(path)
        super().__init__(self.sd.r)

    async def get(self, again=False):  # noqa: D102
        self.cfg = await super().get()
        if self.cfg and not again:
            return self.cfg
        cfg = await super().get()
        self.cfg = cfg
        return cfg

    async def set(self, cfg, replace=False, sync=False):
        """
        Update the client's configuration data.

        If @replace is set, the config file is complete and any other items
        will be deleted from the client.

        If @sync is set, the client will reload apps etc. after updating
        the config, by calling the ``x`` command.
        """

        async def _set(p, c):
            # current client cfg
            try:
                ocd = await self.sd.r(p=p)
                if isinstance(ocd, (list, tuple)):
                    ocd, ocl = ocd
                else:
                    ocl = ()
            except KeyError:
                ocd = {}
                ocl = []
                await self.sd.w(p, d={})
            for k, v in c.items():
                if isinstance(k, str) and k.startswith("_"):
                    continue
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
        await _set(Path(), cfg)

        if sync:
            await self.sd.x()  # runs
