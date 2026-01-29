"""
Command tree support for MoaT commands
"""

from __future__ import annotations

from moat.util import NotGiven, attrdict
from moat.lib.micro import (
    AC_use,
    Event,
    L,
    Lock,
    TaskGroup,
    TimeoutError,  # noqa:A004
    log,
    wait_for_ms,
)
from moat.lib.rpc import BaseCmd

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class BaseSuperCmd(BaseCmd):
    """
    A handler that can have a nested app (or more than one).

    Sets up a taskgroup for the sub-app(s) to run in.
    """

    tg: TaskGroup = None
    app_lock: Lock = None

    async def setup(self) -> None:
        "setup apps"
        await super().setup()
        self.app_lock = Lock()
        self.tg = await AC_use(self, TaskGroup())
        await AC_use(self, self.tg.cancel)

    async def start_app(self, app: BaseCmd) -> None:
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

    sub: dict[str, BaseCmd]

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
        self.root.cfg_reloaded(self.cfg)

        await super().reload()
        for app in list(self.sub.values()):
            await app.reload()

    def find_sub(self, scmd: str, prefix: str = "") -> Callable | None:
        """
        Resolve a subcommand.

        This version uses the ``sub`` mapping.
        """
        if not prefix and (sub := self.sub.get(scmd, None)) is not None:
            return sub

        return super().find_sub(scmd, prefix)

    doc_dir_ = dict(
        _d="list cmd subdirectory",
        d="dict(str,name):sub-apps",
        c=["str:commands"],
        v="bool:show hidden",
    )

    async def cmd_dir_(self, v=True):
        "dir: add subdirs"
        res = await super().cmd_dir_(v=v)
        dd = {}
        for k, v in self.sub.items():
            if not isinstance(k, str) or v is (k[-1] == "_"):
                continue
            try:
                dd[k] = v.cfg["app"]
            except (AttributeError, KeyError):
                dd[k] = v.__class__.__name__
        if dd:
            res["d"] = dd
        return res


class DirCmd(BaseSubCmd):
    """
    A BaseSubCmd handler with apps started by local configuration.

    Not typically subclassed.
    """

    doc = dict(_c=dict(_d="subdirectory", _n="app:sub-apps"))

    SKIP_RDY = True

    def __init__(self, cfg):
        super().__init__(cfg)
        self._did_update = Event()
        self._updated = Event()

    def _updated(self):
        self._did_update.set()

    async def task(self):
        "Monitor task for updating"
        try:
            while True:
                self.cfg.updated_ = self._updated.set
                await self._setup_apps()
                self._did_update.set()
                self._did_update = Event()

                await self._updated.wait()
                self._updated = Event()
                while True:
                    try:
                        await wait_for_ms(250, self._updated.wait)
                    except TimeoutError:
                        break
                    else:
                        self._updated = Event()
        finally:
            del self.cfg.updated_

    async def reload(self):
        "called after the config has been updated"
        await super().reload()
        self._updated.set()
        await self._did_update.wait()

    cmd_upd_ = reload

    async def _setup_apps(self):
        from moat.lib.rpc import LoadCmd  # noqa: PLC0415

        log("Setup %s: %s", self, self.path)
        gcfg = self.cfg
        self.root.cfg_reloaded(gcfg)

        apps = {}
        for k, v in gcfg.items():
            try:
                if not v.get("running", True):
                    continue
                nam = v.get("app", None)
                if not isinstance(nam, str):
                    raise ValueError(f"Bad Config: app-{k}")  # noqa:TRY004
                apps[k] = v
            except (AttributeError, KeyError):
                continue

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

            cfg = gcfg.get(name, attrdict())
            await self.attach(name, LoadCmd(cfg))

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
