"""
Command tree support for MoaT commands
"""

from __future__ import annotations

import sys

from functools import partial

from moat.util import attrdict, import_, Path
from moat.micro.compat import wait_for_ms, log, TaskGroup, ACM, AC_exit, TimeoutError, Event, idle
from moat.micro.cmd.util import StoppedError

from .base import BaseCmd


class BaseLayerCmd(BaseCmd):
    """
    A handler for a single nested app.

    This handler doesn't affect the command hierarchy.
    Its own commands, if any, are reachable by adding "_f" to their name.
    """
    app = None

    async def run(self):
        await idle()

    async def wait_ready(self):
        await self.app.wait_ready()

    async def wait_dead(self):
        await self.app.wait_dead()

    async def run_app(self):
        """
        Run the underlying app.

        By default, just call it.
        """
        await self.app.run_sub()

    async def dispatch(self, action, msg, **kw):
        if len(action) == 1:
            return await super().dispatch(action, msg, **kw)
        else:
            if isinstance(self.app._ready, Exception):
                raise StoppedError() from self.app._ready
            return await self.app.dispatch(action, msg, **kw)

    def __getattr__(self, k):
        if k.endswith("_f"):
            return getattr(self,k[:-2])
        return getattr(self.app, k)


class BaseFwdCmd(BaseLayerCmd):
    """
    A handler for a single nested app that's configured locally.
    """
    async def start(self):
        """
        Start the underlying app
        """
        if self.root.APP is None:
            return
        gcfg = self.cfg
        name = gcfg.get("app", None)
        cfg = gcfg.get("cfg", {})
        tg = self.tg
        log("Setup %s: %s", self.path,name)

        if name is None:
            if self.app is not None:
                self.app.th.cancel()
                self.app = None
            return

        def imp(name):
            return import_(f"{self.root.APP}.{name}", 1)

        self.app = app = imp(name)(cfg)

        await super().start()

        app.attached(self._parent, name)

        async with app.start_lock:
            app.th = await self.tg.spawn(self.run_app, _name=f"r_at_{app.path}")

        await app.wait_ready()
        self.set_ready()


class BaseSubCmd(BaseCmd):
    """
    A handler for a directory.

    Apps have a hierarchical structure. This class serves as the equivalent
    of a subdirectory.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.sub = {}

    async def wait_ready(self):
        "delay until this subtree is up"
        await super().wait_ready()
        while True:
            n = len(self.sub)
            for k,v in list(self.sub.items()):
                await v.wait_ready()
                # TODO warn when delayed
            if len(self.sub) == n:
                break

    async def attach(self, name, app, run=True):
        """
        Attach a named command handler to me and run it.
        """
        await self.detach(name)
        self.sub[name] = app
        app.attached(self, name)
        if run:
            async with app.start_lock:
                if app.th is None:
                    app.th = await self.tg.spawn(app.run_sub, _name=f"r_at_{app.path}")

    async def detach(self, name, w=True):
        """
        Detach a named command handler from me and kill its task.

        Waits for the subtask to end.
        """
        try:
            app = self.sub.pop(name)
        except KeyError:
            return
        try:
            await app.stop(w=w)
        except AttributeError:
            pass
        finally:
            app._parent = None
            app._name = None
            app.root = None


    async def dispatch(self, action: list[str], msg: dict, **kw):
        """
        Dispatch a message to subcommands.

        See `BaseCmd.dispatch` for details.
        """

        if not action:
            raise RuntimeError("NoCmd")
        elif len(action) == 1:
            return await super().dispatch(action, msg, **kw)
        else:
            sub = self.sub[action[0]]
            action = action[1:]
            return await sub.dispatch(action, msg, **kw)

    def cmd__dir(self, h=False):
        res = super().cmd__dir(h=h)
        res["d"] = list(self.sub.keys())
        return res


class BaseDirCmd(BaseSubCmd):
    """
    A BaseSubCmd handler with apps started by local configuration.
    """

    async def start(self):
        await self._setup_apps()

    async def run(self):
        # no-op; readiness is signalled by setup
        await idle()

    async def _start(self):
        await super()._start()
        for k,v in self.sub.items():
            if isinstance(v, BaseCmd):
                async with v.start_lock:
                    if v.th is None:
                        log("Startup %s",self.path/k)
                        v.th = await self.tg.spawn(v.run_sub, _name=f"r_st_{v.path}")

    async def reload(self):
        "called after the config has been updated"
        await self._setup_apps()
        return True

    async def _setup_apps(self):
        # TODO send errors back
        log("Setup %s", self.path)
        if self.root.APP is None:
            return
        gcfg = self.cfg
        # from pprint import pprint
        # pprint(gcfg,sys.stderr)
        apps = gcfg.get("apps", {})
        tg = self.tg

        def imp(name):
            return import_(f"{self.root.APP}.{name}", 1)

        for name in list(self.sub.keys()):
            if name not in apps:
                app = self.sub[name]
                await self.detach(name)  # pylint: disable=protected-access
                sys.modules.pop(app.__module__, None)

        # First, setup the app data structures
        for name, v in apps.items():
            if name in self.sub:
                continue

            cfg = gcfg.get(name, {})
            try:
                await self.attach(name, imp(v)(cfg), run=False)
            except TypeError as exc:
                raise # TypeError(f"{name}: {v} {repr(imp(v))} {repr(exc)}: {repr(cfg)}")

        # Second, run them all.
        # For existing apps, tell it to update its configuration.
        for name, app in self.sub.items():
            async with app.start_lock:
                if app.th is not None:
                    cfg = getattr(gcfg, name, attrdict())
                    app._rl_ok = await app.reload()
                else:
                    app.th = await tg.spawn(  # pylint: disable=protected-access
                        app.run_sub, _name=f"mp_{self.path/name}"
                    )

        # Third, wait for them to be up.
        for k,v in self.sub.items():
            if isinstance(v._ready,Event):
                try:
                    await wait_for_ms(250, v._ready.wait)
                except TimeoutError:
                    log("* Waiting for App %s", v.path)
                    await v._ready.wait()
                    log("* OK wait for App %s", v.path)

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
            await tg.spawn(self.run_sub, _name="DispatchMain")
            await self.wait_ready()
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

    @property
    def root(self):
        return self

    @property
    def path(self):
        return Path()


class SubDispatch:
    """
    A Dispatch forwarder that prefixes a path.

    Calls are executed directly if possible.

    Do not call this before the object hierarchy is assembled.
    Otherwise your code will be inefficient.
    """
    def __init__(self, dispatch, path):
        for i,p in enumerate(path):
            try:
                dispatch = dispatch.sub[p]
            except (AttributeError,KeyError):
                self._dest = dispatch
                self._rem = path[i:]
                break
        else:
            self._dest = dispatch
            self._rem = ()
            for k in dir(dispatch):
                if k.startswith("cmd"):
                    setattr(self, k[4:], getattr(dispatch,k))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    def _send(self, *a, _x_err=(), **k):
        return self._dest.dispatch(self._rem + a, k, x_err=_x_err)

    def __getattr__(self, k):
        """
        Enables code like:
            s = d.get_sub("a","b")
            await s.c()
        which calls the subhandler at "a.b"'s `cmd_c` method.

        Note that non-keyword arguments access subcommands (or try to do so).
        """
        if k[0] == "_":
            raise AttributeError(k)
        return partial(self._send, k)

    def __call__(self, *a, _x_err=(), **k) -> Async:
        """
        Enables code like:
            s = d.get_sub("a","b","c")
            await s()
        which calls the subhandler at "a.b"'s `cmd_c` method.

        Note that non-keyword arguments access subcommands (or try to do so).
        """
        if self._rem or a:
            return self._dest.dispatch(self._rem + a, k, x_err=_x_err)
        else:
            return self._dest.cmd(**k)
