"""
Command tree support for MoaT commands
"""

from __future__ import annotations

import sys

from moat.util import attrdict, import_, Path
from moat.micro.compat import wait_for_ms, log, TaskGroup, ACM, AC_exit, TimeoutError, Event

from .base import BaseCmd

class BaseDirCmd(BaseCmd):
    """
    A handler for a directory with apps.

    Apps have a hierarchical structure. This class serves as the equivalent
    of a subdirectory.
    """

    async def run(self):
        async with TaskGroup() as self._tg:
            await self._setup_apps()
            await super().run()

    async def update_config(self):
        "called after the config has been updated"
        await self._setup_apps()

    async def _setup_apps(self):
        # TODO send errors back
        log("Setup %s", self.path)
        if self.root.APP is None:
            return
        gcfg = self.cfg
        apps = gcfg.get("apps", {})
        tg = self._tg

        def imp(name):
            return import_(f"{self.root.APP}.{name}", 1)

        for name in list(self._sub.keys()):
            if name not in apps:
                app = self._sub[name]
                self.detach(app)  # pylint: disable=protected-access
                sys.modules.pop(app.__module__, None)

        # First, setup the app data structures
        for name, v in apps.items():
            if name in self._sub:
                continue

            cfg = gcfg.get(name, {})
            try:
                await self.attach(name, imp(v)(cfg), run=False)
            except TypeError as exc:
                raise TypeError(f"{name}: {v} {repr(imp(v))} {repr(exc)}: {repr(cfg)}")

        # Second, run them all.
        # For existing apps, tell it to update its configuration.
        for name, app in self._sub.items():
            async with app._start_lock:
                if app._ts is not None:
                    cfg = getattr(gcfg, name, attrdict())
                    await app.config_updated(cfg)
                else:
                    app._ts = await tg.spawn(  # pylint: disable=protected-access
                        app._run_, _name=f"mp_{self.path/name}"
                    )

        # Third, wait for them to be up.
        for k,v in self._sub.items():
            if isinstance(v._ready,Event):
                try:
                    await wait_for_ms(250, v._ready.wait)
                except TimeoutError:
                    log("* Waiting for App:%s", v.path)
                    await v._ready.wait()

        self.set_ready()


class Dispatch(BaseDirCmd):
    """
    This is the system's root dispatcher.

    Call "send" with an action (a string or list) and either a single
    parameter or some key/value data. The response is returned / raised.
    """

    APP = "app"

    def __init__(self,cfg):
        super().__init__(cfg)

    async def __aenter__(self):
        acm = ACM(self)
        try:
            tg = await acm(TaskGroup())
            log("Start Main Run")
            await tg.spawn(self._run, _name="DispatchMain")
            await self.wait_all_ready()
            await acm(tg.cancel)
            return self
        except BaseException as exc:
            if not await AC_exit(self, type(exc),exc,getattr(exc,"__traceback__",None)):
                raise

    async def __aexit__(self, *tb):
        return await AC_exit(self, *tb)

    def sub_at(self, *p):
        from .tree import SubDispatch
        return SubDispatch(self, p)

    def cfg_at(self, *p):
        from .tree import CfgStore
        return CfgStore(self, p)

    @property
    def root(self):
        return self

    @property
    def path(self):
        return Path()
