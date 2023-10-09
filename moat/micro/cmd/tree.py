"""
Server side of BaseCmd
"""

from moat.util import attrdict, NotGiven

from ._tree import Dispatch as _Dispatch

class Dispatch(_Dispatch):
    APP = "moat.micro.app"

class SubDispatch:
    """
    A Dispatch forwarder that prefixes a path
    """
    def __init__(self, dispatch, path):
        self.disp = dispatch
        self.path = path

    async def send(self, *a, **k):
        return await self.disp.dispatch(self.path+a, k)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

class CfgStore(SubDispatch):
    """
    Config file storage.

    The subpath points to the destination's "cfg.Cmd" app.
    """
    cfg:dict = None
    subpath = ()

    async def get(self, again=False):
        """
        Collect the client's configuration data.
        """
        async def _get(p):
            d = await self.send("r", p=p)
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
                ocd = await self.send("r", p=p)
                if isinstance(ocd, (list, tuple)):
                    ocd, ocl = ocd
                else:
                    ocl = ()
            except KeyError:
                ocd = {}
                ocl = []
                await self.send("w", p=p, d={})
            for k, v in c.items():
                if isinstance(v, dict):
                    await _set(p + (k,), v)
                elif ocd.get(k, NotGiven) != v:
                    await self.send("w", p=p + (k,), d=v)

            if not replace:
                return
            # drop those client cfg snippets that are not on the server
            for k in chain(ocd.keys(), ocl):
                if k not in c:
                    await self.send("w", p=p + (k,), d=NotGiven)

        self.cfg = None
        await _set(self.subpath, cfg)

        if sync:
            await self.send("x")  # runs

