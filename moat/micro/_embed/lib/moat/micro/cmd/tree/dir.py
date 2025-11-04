"""
Command tree support for MoaT commands
"""

from __future__ import annotations

from moat.util import NotGiven, Path, import_
from moat.lib.cmd.base import MsgSender
from moat.lib.cmd.errors import ShortCommandError
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import AC_use, Event, L, Lock, TaskGroup, log

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.cmd import Msg

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
            res = await super().wait_ready(wait=wait)
            if res is None:
                return None
            for app in list(self.sub.values()):
                if (w := await app.wait_ready(wait=wait)) is None:
                    return None
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

    async def handle(self, msg: Msg, rcmd: list, *prefix: list[str]):
        """
        Dispatch a message to subcommands.

        See `BaseCmd.handle` for details.
        """

        if not rcmd:
            raise ShortCommandError

        cmd = rcmd[-1]
        if isinstance(cmd, str) and cmd[0] == "!":
            rcmd[-1] = cmd[1:]
        elif not prefix and (sub := self.sub.get(cmd, None)) is not None:
            rcmd.pop()
            return await sub.handle(msg, rcmd)
        return await super().handle(msg, rcmd, *prefix)

    doc_dir_ = dict(
        _d="list cmd subdirectory",
        d="dict(str,name):sub-apps",
        c=["str:commands"],
        v="bool:show hidden",
    )

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
            if v is NotGiven:
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
        self._sender = MsgSender(self)

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

    @property
    def root(self) -> Dispatch:
        "root dispatcher"
        return self

    @property
    def path(self):
        "root path"
        return Path()

    @property
    def cmd(self):
        "root command sender"
        return self._sender.cmd

    @property
    def sub_at(self):
        "root subcommand resolver"
        return self._sender.sub_at

    @property
    def cfg_at(self):
        "config subcommand resolver"
        return self._sender.cfg_at
