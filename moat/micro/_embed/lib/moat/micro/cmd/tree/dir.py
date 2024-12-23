"""
Command tree support for MoaT commands
"""

from __future__ import annotations

from functools import partial

from moat.util import Path, import_, P
from moat.micro.cmd.base import ACM_h, BaseCmd, ShortCommandError
from moat.micro.compat import AC_use, Event, L, Lock, TaskGroup, log
from moat.micro.errors import NoPathError

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import AsyncContextManager
    from collections.abc import Awaitable


class BaseSuperCmd(BaseCmd):
    """
    A handler that can have a nested app (or more than one).

    Sets up a taskgroup for the sub-app(s) tp run in.
    """

    tg: TaskGroup = None
    app_lock: Lock = None

    async def setup(self):
        "setup apps"
        await super().setup()
        self.app_lock = Lock()
        self.tg = await AC_use(self, TaskGroup())
        await AC_use(self, self.tg.cancel)

    async def start_app(self, app):
        """
        Run (or reload) this app.
        """

        async def _run(app):
            try:
                await app.run()
            finally:
                app.p_task = None

        async with self.app_lock:
            if app.p_task:
                await app.reload()
                return
            try:
                t = await self.tg.spawn(_run, app)
                if app.p_task is False:
                    # set by .stop()
                    t.cancel()
                    app.p_task = None
                    return

                app.p_task = t
                if L:
                    await app.wait_started()
            except BaseException:
                app.p_task = None
                raise


class BaseSubCmd(BaseSuperCmd):
    """
    A handler for a directory.

    Apps have a hierarchical structure. This class serves as the equivalent
    of a subdirectory.

    How to create new entries is not specified in this class.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.sub = {}

    if L:

        async def wait_ready(self, wait=True):
            """Delay until this subtree is up,

            Returns True if all sub-apps are stopped.
            """
            await super().wait_ready(wait=wait)
            again = True
            res = False
            while again:
                again = False
                if res:
                    # if all apps were dead, maybe they are not now
                    res = False
                for app in list(self.sub.values()):
                    if (w := await app.wait_ready(wait=wait)) is None:
                        if not wait:
                            return None
                        again = True
                        res = None
                    elif res is not None:
                        res &= w
            return res

    async def attach(self, name, app) -> None:
        """
        Attach a sub-handler to me.

        An existing handler with this name is stopped.
        """
        oa = self.sub.pop(name, None)
        if app is not None:
            self.sub[name] = app
            app.attached(self, name)
        if oa is not None:
            await oa.stop()

    def detach(self, name) -> Awaitable:
        """
        Detach and stop a command handler.
        """
        return self.attach(name, None)

    async def reload(self):
        "reload apps"
        await super().reload()
        for app in list(self.sub.values()):
            await app.reload()

    async def dispatch(self, action: list[str], msg: dict, **kw):
        """
        Dispatch a message to subcommands.

        See `BaseCmd.dispatch` for details.
        """

        if not action:
            raise ShortCommandError
        if len(action) == 1:
            return await super().dispatch(action, msg, **kw)

        try:
            sub = self.sub[action[0]]
        except KeyError:
            raise NoPathError(
                self.path,
                action,
                self.__class__.__name__,
                await self.cmd_dir_(v=None),
            ) from None
        action = action[1:]
        return await sub.dispatch(action, msg, **kw)

    async def cmd_dir_(self, v=True):
        "dir: add subdirs"
        res = await super().cmd_dir_(v=v)
        res["d"] = {
            k: v.__class__.__name__
            for k, v in self.sub.items()
            if not isinstance(k, str) or v is not (k[-1] == "_")
        }
        return res


class DirCmd(BaseSubCmd):
    """
    A BaseSubCmd handler with apps started by local configuration.

    Not typically subclassed.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self._did_update = Event()
        self._updated = Event()

    async def task(self):
        "Monitor task for updating"
        if self.root.APP is None:
            raise RuntimeError("Root no APP")
        while True:
            await self._setup_apps()
            self._did_update.set()
            self._did_update = Event()

            await self._updated.wait()
            self._updated = Event()

    async def reload(self):
        "called after the config has been updated"
        await super().reload()
        self._updated.set()
        await self._did_update.wait()

    cmd_upd_ = reload

    async def _setup_apps(self):
        log("Setup %s", self.path)
        gcfg = self.cfg
        # from pprint import pprint
        # pprint(gcfg,sys.stderr)
        apps = gcfg.get("apps", {})

        def imp(name):
            return import_(f"{self.root.APP}.{name}", 1)

        # Zeroth, kill apps that are no longer live
        for name in list(self.sub.keys()):
            if name not in apps:
                await self.detach(name)

        # First, setup the app data structures
        for name, v in apps.items():
            if name in self.sub:
                continue

            cfg = gcfg.get(name, {})
            await self.attach(name, imp(v)(cfg))

        # Second, run them all.
        # For existing apps, tell it to update its configuration.
        for app in self.sub.values():
            await self.start_app(app)

        # Third, wait for them to be up.
        if L:
            for app in self.sub.values():
                if app.cfg.get("wait", True):
                    await app.wait_ready()

        # Finally, mark done.
        if L:
            self.set_ready()


class Dispatch(DirCmd):
    """
    This is the system's root dispatcher.

    Call "send" with an action (a string or list) and either a single
    parameter or some key/value data. The response is returned / raised.
    """

    APP = "app"  # Satellite. server must override.

    def __init__(self, cfg, run=False, i=None):
        super().__init__(cfg)
        self._run = run
        self.i = i

    async def __aenter__(self):
        await super().__aenter__()
        try:
            if self._run:
                await self.tg.spawn(self.task)
                if L:
                    await self.wait_ready()
        except BaseException as exc:
            await super().__aexit__(type(exc), exc, None)
            raise
        return self

    def sub_at(self, p: str | Path):
        """
        Returns a SubDispatch to this path.

        You can call this either with a sequence of path elements
        or with a path.
        """
        if isinstance(p, str):
            p = P(p)
        return SubDispatch(self, p)

    @property
    def root(self) -> Dispatch:
        "root dispatcher"
        return self

    @property
    def path(self):
        "root path"
        return Path()


def SubDispatch(dispatch, path):
    """
    A Dispatch forwarder that prefixes a path.

    Calls are executed directly if possible.

    Create this object in your ``setup`` method.
    Using it from ``__init__`` results in ineficient call execution.

    You can then use::

            s = d.get_sub("a","b")
            await s.c()

    as a fast shorthand for ``await d.send("a","b","c")``.

    Non-keyword arguments access subcommands (or try to do so).

    It's also possible to access iterators this way: an ``it_X`` attribute
    accesses the destination's ``iter_X`` method. As with
    `dispatch.send_iter`, the timer is the first argument.

    This is a constructor. The actual class is ``_SubDispatch``.
    """

    for i, p in enumerate(path):
        try:
            dispatch = dispatch.sub[p]
        except (AttributeError, KeyError):
            return _SubDispatch(path, dispatch, path[i:])

    # Cache the subdispatcher for this app
    try:
        sd = dispatch._subD  # noqa:SLF001
    except AttributeError:
        sd = _SubDispatch(path, dispatch, ())

        for k in dir(dispatch):
            if k.startswith("cmd_"):
                setattr(sd, k[4:], getattr(dispatch, k))
        dispatch._subD = sd  # noqa:SLF001
    return sd


class _SubDispatch:
    def __init__(self, path, dest, rem):
        self._path = path
        self._dest = dest
        self._rem = rem
        assert isinstance(rem, (tuple, list, Path))

    @property
    def root(self) -> Dispatch:
        "root dispatcher"
        return self._dest.root

    if L:

        def wait_ready(self, wait: bool = True) -> Awaitable:
            "forwards to the destination"
            return self._dest.wait_ready(wait=wait)

    def sub_at(self, p: Path):
        "create a sub-subdispatcher"
        return SubDispatch(self.root, self._path + p)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    def dispatch(self, a, msg, **kw) -> Awaitable:
        "Forward an explicit dispatch call"
        return self._dest.dispatch(self._rem + a, msg, **kw)

    def _send(self, *a, _x_err=(), **k) -> Awaitable:
        return self._dest.dispatch(self._rem + a, k, x_err=_x_err)

    def _send_r(self, _a, _rep, *a, _x_err=(), **kw) -> AsyncContextManager:
        return ACM_h(self._dest.dispatch, self._rem + (_a,) + a, kw, rep=_rep, x_err=_x_err)

    def __getattr__(self, k):
        if k[0] == "_":
            raise AttributeError(k)
        if k[:3] == "it_":
            return partial(self._send_r, k[3:])
        else:
            return partial(self._send, k)

    def __call__(self, *a, _x_err=(), **k) -> Awaitable:
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
