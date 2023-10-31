"""
Command tree support for MoaT commands
"""

from __future__ import annotations

from functools import partial

from moat.util import Path, import_
from moat.micro.compat import AC_use, Event, TaskGroup, log

from .base import ACM_h, BaseCmd, ShortCommandError

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import AsyncContextManager, Awaitable, Never

    from moat.micro.proto.stack import BaseBuf, BaseMsg
    from moat.micro.stacks.util import BaseConnIter


__all__ = [
    "DirCmd",
    "BaseSuperCmd",
    "BaseFwdCmd",
    "BaseLayerCmd",
    "BaseSubCmd",
    "BaseListenCmd",
    "BaseListenOneCmd",
    "Dispatch",
    "SubDispatch",
]


class BaseSuperCmd(BaseCmd):
    """
    A handler that can have a nested app (or more than one).

    Sets up a taskgroup for the sub-app(s) tp run in.
    """

    tg: TaskGroup = None

    async def setup(self):
        await super().setup()
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

        if app.p_task:
            await app.reload()
            return
        if app.p_task is False:
            raise RuntimeError("DupStartB")
        app.p_task = False
        try:
            app.p_task = await self.tg.spawn(_run, app)
        except BaseException:
            app.p_task = None
            raise


class BaseLayerCmd(BaseSuperCmd):
    """
    A handler for a single nested app.

    This handler doesn't affect the command hierarchy.
    Its own commands, if any, are reachable by adding "_f" to their name.

    Alternately, the nested app is named "_".

    You need to override "gen_cmd" to create the app object.
    """

    app = None
    name = "_"

    async def run_app(self):
        """
        The command handler's executor. By default, calls `self.app.run`
        within the command's context.

        You might override this e.g. for restarting or
        shielding the rest of MoaT from errors.
        """
        await self.app.run()

    async def task(self):
        """
        Run the app as a subtask.

        You typically don't override this.
        """
        async with TaskGroup() as tg:
            if self.app is not None:
                await tg.spawn(self.run_app)
            await self.app.wait_ready()
            self.set_ready()

            # await self.app.stopped()
            # the return from the taskgroup already does that

    async def setup(self):
        await super().setup()
        self.app = await self.gen_cmd()
        if self.app is not None:
            self.app.attached(self, self.name)
            self.set_ready()

    async def reload(self):
        await super().reload()
        if self.app is not None:
            await self.app.reload()

    async def wait_ready(self, wait=True):
        if await super().wait_ready(wait=wait):
            return True
        if self.app is None:
            return None
        return await self.app.wait_ready(wait=wait)

    async def gen_cmd(self) -> BaseCmd:
        """
        Create the actual app to use.

        The default uses `None` and leaves the setup to `task`.
        """
        return None

    async def dispatch(self, action, msg, **kw):
        """
        Forward to the sub-app unless specifically directed not to.
        """
        if len(action) > 1:
            if action[0] == self.name:
                action = action[1:]
            elif action[0] == f"!{self.name}":
                action = action[1:]
                return await super().dispatch(action, msg, **kw)
        elif action[0] == "dir":
            res = await self.app.dispatch(action, msg, **kw)
            res.setdefault("d", []).append(f"!{self.name}")
            return res

        if self.app is None:
            await self.wait_ready()
        return await self.app.dispatch(action, msg, **kw)

    def set_ready(self):
        if self.app is None:
            raise RuntimeError("early")
        super().set_ready()

    def __getattr__(self, k):
        if k.startswith("_"):
            raise AttributeError(k)
        if k.endswith("_f"):
            return getattr(self, k[:-2])
        return getattr(self.app, k)


class BaseFwdCmd(BaseLayerCmd):
    """
    A handler for a single nested app that's configured locally.
    """

    async def gen_cmd(self):
        """
        Create the underlying app object
        """
        if self.root.APP is None:
            raise RuntimeError("WhereApp")
        gcfg = self.cfg
        name = gcfg.get("app", None)
        cfg = gcfg.get("cfg", {})
        log("Setup %s: %s", self.path, name)

        if name is None:
            if self.app is not None:
                self.app.stop()
                self.app = None
            return

        def imp(name):
            return import_(f"{self.root.APP}.{name}", 1)

        return imp(name)(cfg)


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

        sub = self.sub[action[0]]
        action = action[1:]
        return await sub.dispatch(action, msg, **kw)

    async def cmd_dir(self, h=False):
        res = await super().cmd_dir(h=h)
        res["d"] = list(self.sub.keys())
        return res


class BaseListenOneCmd(BaseLayerCmd):
    """
    An app that runs a listener and accepts a single connection.

    Override `listener` to return it.

    TODO: this needs to be a stream layer instead: we want the
    Reliable module to be able to pick up where it left off.
    """

    def listener(self) -> BaseConnIter:
        """
        How to get new connections. Returns a BaseConnIter.

        Must be implemented in your subclass.
        """
        raise NotImplementedError

    def wrapper(self, conn) -> BaseMsg:
        """
        How to wrap the connection so that you can communicate on it.

        By default, use `console_stack`.
        """
        # pylint:disable=import-outside-toplevel
        from moat.micro.stacks.console import console_stack

        return console_stack(conn, self.cfg)

    async def reject(self, conn: BaseBuf):
        """
        Close the connection.
        """
        # an async context should do it
        async with conn:
            pass

    async def handler(self, conn):
        """
        Process a connection
        """
        from moat.micro.cmd.stream import ExtCmdMsg  # pylint:disable=import-outside-toplevel

        app = ExtCmdMsg(self.wrapper(conn), self.cfg)
        if (
            self.app is None
            or not self.app.is_ready()
            or self._running
            or self.cfg.get("replace", True)
        ):
            if self.app is not None:
                await self.app.stop()
            app.attached(self, "_")
            self.app = app
            await self.start_app(app)
            self.set_ready()
            await app.wait_ready()

            await app.wait_stopped()
            if self.app is app:
                self.app = None
        else:
            # close the thing
            await self.reject(conn)

    async def task(self) -> Never:
        """
        Accept connections.
        """
        async with self.listener() as conns:
            async for conn in conns:
                await self.tg.spawn(self.handler, conn)


class BaseListenCmd(BaseSubCmd):
    """
    An app that runs a listener and connects all incoming connections
    to numbered subcommands.

    Override `listener` to return an async context manager / iterator.
    """

    seq = 1

    # no multiple inheritance for MicroPython
    listener = BaseListenOneCmd.listener
    wrapper = BaseListenOneCmd.wrapper

    async def handler(self, conn):
        """
        Process a new connection.
        """
        from moat.micro.cmd.stream import ExtCmdMsg  # pylint:disable=import-outside-toplevel

        conn = self.wrapper(conn)
        app = ExtCmdMsg(conn, self.cfg)
        seq = self.seq
        if seq > len(self.sub) * 3:
            seq = 10
        while seq in self.sub:
            seq += 1
        self.seq = seq + 1
        await self.attach(seq, app)
        await self.start_app(app)
        await app.wait_ready()

        await app.wait_stopped()
        await self.detach(seq)

    async def task(self) -> Never:
        """
        Accept connections.
        """
        async with self.listener() as conns:
            self.set_ready()
            async for conn in conns:
                await self.tg.spawn(self.handler, conn)


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
        self._updated.set()
        await self._did_update.wait()

    cmd_upd = reload

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
        for app in self.sub.values():
            if app.cfg.get("wait", True):
                await app.wait_ready()

        # Finally, mark done.
        self.set_ready()


class Dispatch(DirCmd):
    """
    This is the system's root dispatcher.

    Call "send" with an action (a string or list) and either a single
    parameter or some key/value data. The response is returned / raised.
    """

    APP = None  # server / satellite must override

    def __init__(self, cfg, run=False):
        super().__init__(cfg)
        self._run = run

    async def __aenter__(self):
        await super().__aenter__()
        try:
            if self._run:
                await self.tg.spawn(self.task)
                await self.wait_ready()
        except BaseException as exc:
            await super().__aexit__(type(exc), exc, None)
            raise
        return self

    def sub_at(self, *p):
        "returns a SubDispatch to this path"
        # pylint:disable=import-outside-toplevel,cyclic-import,redefined-outer-name
        from .tree import SubDispatch

        return SubDispatch(self, p)

    @property
    def root(self) -> Dispatch:
        "root dispatcher"
        return self

    @property
    def path(self):
        "root path"
        return Path()


class SubDispatch:
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
    """

    def __init__(self, dispatch, path):
        self._path = path  # for creating sub-subdispatcher

        for i, p in enumerate(path):
            try:
                dispatch = dispatch.sub[p]
            except (AttributeError, KeyError):
                self._dest = dispatch
                self._rem = path[i:]
                break
        else:
            self._dest = dispatch
            self._rem = ()
            for k in dir(dispatch):
                if k.startswith("cmd_"):
                    setattr(self, k[4:], getattr(dispatch, k))

    @property
    def root(self) -> Dispatch:
        "root dispatcher"
        return self._dest.root

    def wait_ready(self) -> Awaitable:
        "forwards to the destination"
        return self._dest.wait_ready()

    def sub_at(self, *p):
        "create a sub-subdispatcher"
        from .tree import SubDispatch

        return SubDispatch(self, self._path + p)

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
