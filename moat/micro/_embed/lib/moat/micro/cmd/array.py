"""
A command that accesses a row of mostly-identical subcommands
"""

from __future__ import annotations

from moat.util import import_, combine_dict

from .tree import BaseSuperCmd
from .util import set_part

class ArrayCmd(BaseSuperCmd):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.apps = []
    
    async def setup(self):
        await super().setup()
        await self._setup_apps()

    async def wait_ready(self, wait=True):
        """Delay until this subtree is up,

        Returns True if any sub-apps are stopped.
        """
        await super().wait_ready(wait=wait)
        again = True
        res = False
        while again:
            again = False
            for app in self.apps:
                if (w := await app.wait_ready(wait=wait)) is None:
                    if not wait:
                        return None
                    again = True
                    res = None
                elif w is True:
                    return True
        return res

    async def attach(self, name, app) -> None:
        """
        Attach a sub-handler to me.

        An existing handler with this name is stopped.
        """
        try:
            oa = self.apps[name]
        except IndexError:
            if len(self.apps) != name:
                raise
            self.apps.append(app)
            oa = None
        else:
            self.apps[name] = app
        app.attached(self, name)
        if oa is not None:
            await oa.stop()

    def detach(self, name) -> Awaitable:
        """
        Detach and stop a command handler.
        """
        return self.attach(name, None)

    def _cfg(self, i):
        cfg = combine_dict(self.cfg.get("cfg", {}), self.cfg.get(i, {}))
        if (ii := self.cfg.get("i",None)) is not None:
            set_part(cfg,ii, i+self.cfg.get("i_off", 0))
        return cfg

    async def reload(self):
        await super().reload()
        self.n = self.cfg["n"]
        for i,app in enumerate(self.apps):
            app.cfg.merge(self._cfg(i))
            await app.reload()
        while len(self.apps) > self.n:
            app = self.apps.pop()
            await self.detach(len(self.apps))

    async def _setup_apps(self):
        name = self.cfg["app"]
        cls = import_(f"{self.root.APP}.{name}", 1)

        self.n = self.cfg["n"]
        for i in range(self.n):
            app = cls(self._cfg(i))
            await self.attach(i, app)

        for app in self.apps:
            await self.start_app(app)

    async def dispatch(self, action: list[str], msg: dict, **kw):
        """
        Dispatch a message to subcommands.

        See `BaseCmd.dispatch` for details.
        """

        if not action:
            raise RuntimeError("NoCmd")
        if len(action) == 1:
            return await super().dispatch(action, msg, **kw)

        sub = self.apps[action[0]]
        return await sub.dispatch(action[1:], msg, **kw)

    async def cmd_all(self, a, d={}, s=None, e=None):
        """
        Call all sub-apps and collect the result.
        """
        res = []
        for app in self.apps[s:e]:
            res.append(await app.dispatch(a, d))

        return res

