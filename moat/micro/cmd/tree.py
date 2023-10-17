"""
Server side of BaseCmd
"""

from itertools import chain

from moat.util import attrdict, NotGiven

from ._tree import *
from ._tree import Dispatch as _Dispatch


class Dispatch(_Dispatch):
    APP = "moat.micro.app"

    def cfg_at(self, *p):
        return CfgStore(self, p)


class CfgStore:
    """
    Config file storage.

    The subpath points to the destination's "cfg.Cmd" app.
    """
    cfg:dict = None
    subpath = ()

    def __init__(self, dispatch, path):
        self.sd = dispatch.sub_at(*path)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    async def get(self, again=False):
        """
        Collect the client's configuration data.
        """
        async def _get(p):
            d = await self.sd.r(p=p)
            if isinstance(d, (list, tuple)):
                d, s = d
                if isinstance(d, dict):
                    d = attrdict(d)
                for k in s:
                    d[k] = await _get(p + (k,))
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
            try:
                try:
                    ocd = await self.sd.r(p=p, _x_err=(KeyError,))
                except TypeError:
                    # local version, not dispatched
                    ocd = await self.sd.r(p=p)
                if isinstance(ocd, (list, tuple)):
                    ocd, ocl = ocd
                else:
                    ocl = ()
            except KeyError:
                ocd = {}
                ocl = []
                await self.sd.w(p=p, d={})
            for k, v in c.items():
                if isinstance(v, dict):
                    await _set(p + (k,), v)
                elif ocd.get(k, NotGiven) != v:
                    await self.sd.w(p=p + (k,), d=v)

            if not replace:
                return
            # drop those client cfg snippets that are not on the server
            for k in chain(ocd.keys(), ocl):
                if k not in c:
                    await self.sd.w(p=p + (k,), d=NotGiven)

        self.cfg = None
        await _set(self.subpath, cfg)

        if sync:
            await self.sd.x()  # runs
