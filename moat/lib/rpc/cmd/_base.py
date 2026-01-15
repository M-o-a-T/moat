"""
Basic infrastructure to run an RPC system via an unreliable,
possibly-reordering, and/or stream-based transport

We have a stack of classes. At the top there's the adapting App, a subclass
of CmdMsg. Linked to it via a chain of *Msg…Buf modules there's a
*Buf adapter that affords an external interface.

Everything is fully asynchronous. Each class is an async context manager,
responsible for managing the contexts of its sub-app(s) / linked stream(s).

Incoming messages are handled by the child's "dispatch" method. They
are expected to be fully asynchronous, i.e. a "run" method that calls
"dispatch" must use a separate task to do so.

Outgoing messages are handled by the parent's "send" method. Send calls
return when the data has been sent, implying that sending on an
unreliable transport will wait for the message to be confirmed. Sending
may fail.
"""

from __future__ import annotations

import sys

from moat.util import import_
from moat.lib.micro import AC_use, Event, L, Lock, idle
from moat.lib.path import Path
from moat.lib.rpc import MsgHandler, MsgSender
from moat.lib.stream import Base
from moat.micro.cmd.util import wait_complain
from moat.micro.cmd.util.part import enc_part, get_part

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.rpc import BaseSuperCmd

__all__ = ["BaseCmd", "LoadCmd", "LockBaseCmd", "RootCmd"]

APP: str = "app" if sys.implementation.name == "micropython" else "moat.micro.app"


class BaseCmd(MsgHandler):
    """
    Base class of a Command handler.
    """

    root: RootCmd = None
    _parent: BaseSuperCmd = None
    _name: str | None = None
    _ts = None
    _rl_ok = None  # result of last reload
    p_task = None  # managed by parent. Do not touch.

    if L:
        _starting: Event = None
        _ready: Event = None
    _stopped: Event = None

    def __init__(self, cfg):
        cfg._moat_cmd = self  # noqa:SLF001
        super().__init__(cfg)
        # self.cfg = cfg
        self.init_events()

    def init_events(self):
        "Setup events for startup, stopping, and readiness"
        if self._stopped is None:
            if L:
                self._starting = Event()
                self._ready = Event()
            self._stopped = Event()

    def __repr__(self):
        try:
            return f"<{self.__class__.__name__}: {self.path} {(id(self) >> 4) & 0xFFF:03x}>"
        except AttributeError:
            return f"<{self.__class__.__name__}: ?path {(id(self) >> 4) & 0xFFF:03x}>"

    async def setup(self):
        """
        Start up this command.

        Call first when overriding.
        """
        await AC_use(self, self.set_stopped)
        if self._stopped is None:
            self.init_events()
        elif L:
            if self._starting is None or self._starting.is_set():
                raise RuntimeError("DupStartA")

            self._starting.set()
            self._starting = None

    async def teardown(self):
        """
        Clean up this command.

        Call last when overriding.
        """

    async def reload(self):
        """
        Reload from updated config.

        The default does nothing, which is probably the wrong thing to do.
        """

    def set_stopped(self):
        """
        The command has ended.
        """
        if self._stopped is None:
            return
        self._stopped.set()
        self._stopped = None

        if L:
            if self._starting is not None:
                self._starting.set()
                self._starting = None

            if self._ready is not None:
                self._ready.set()
                self._ready = None

    async def run(self):
        """
        Task handler to run this command.

        If you need a subtask, override ``task``.
        """
        async with self:
            await self.task()

    async def task(self):
        """
        The app's task. Runs after ``setup`` has completed. By default does nothing.

        If you override this, you're responsible for eventually calling ``set_ready``.
        Otherwise the MoaT system will stall!
        """
        if L:
            self.set_ready()
        await idle()

    if L:

        def set_ready(self):
            """
            This command is now ready.

            Called internally only!
            """
            self.cfg.pop("_cmd", None)
            if self._starting is not None:
                raise RuntimeError(f"Ready w/o start {self!r}")
                # self._starting.set()
                # self._starting = None
            if self._ready is not None:
                self._ready.set()
                self._ready = None

    async def stop(self):
        "Stop this subcommand"
        if self.p_task is None:
            self.p_task = False
            return  # starting up or not running
        self.p_task.cancel()
        await wait_complain(f"Stop {self.path}", 250, self.wait_stopped)

    cmd_stp_ = stop

    if L:

        async def wait_started(self):
            """
            Wait for the command's setup procedure to commence.
            """
            if self._starting is None:
                return
            await wait_complain(f"Starting {self.path}", 250, self._starting.wait)

        async def wait_ready(self, wait=True) -> bool | None:
            """
            Check if the command is ready.

            Returns True if it is stopped, False if it is already running, and
            None if the command has (or would have, if @wait is False) waited
            for it to become ready.
            """
            if self._stopped is None:
                return True
            if self._ready is None:
                return False
            if wait:
                await wait_complain(f"Rdy {self.path}", 250, self._ready.wait)
            return None

    async def wait_stopped(self):
        "wait until this is no longer running"
        if self._stopped is not None:
            await self._stopped.wait()

    doc_stq_ = dict(_d="wait until no longer running")

    cmd_stq_ = wait_stopped

    @property
    def path(self):
        "calculate the path to myself"
        # XXX cache it?
        if self._name is None:
            return self._parent.path
        return self._parent.path / self._name

    doc_cfg_ = dict(_d="config", _r="parts")

    async def cmd_cfg_(self, p=()):
        """
        Read this item's config.

        Writing is intentionally not supported.
        """
        return enc_part(get_part(self.cfg, p))

    def attached(self, parent: BaseSuperCmd, name: str | None):
        "Tell this Cmd it's attached under this parent, with this name."
        if self._parent is not None:
            raise RuntimeError(f"already {'.'.join(self.path)}")
        self._parent = parent
        self._name = name
        self.root = parent.root


class LockBaseCmd(BaseCmd):
    """
    A BaseCmd that blocks concurrent requests.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._lock = Lock()

    async def handle(self, *a, **kw):
        "strictly serial"
        async with self._lock:
            return await super().handle(*a, **kw)


class LoadCmd(BaseCmd):
    """
    A command loaded from disk.
    """

    def __new__(cls, cfg, **kw):
        if not cfg.get("running", True):
            return None

        def imp(name):
            if name == "dir":
                name = "sub.Dir"
            return import_(f"{APP}.{name}", 1)

        return imp(cfg["app"])(cfg, **kw)

    def __init__(self, cfg, **kw):
        pass


class RootCmd(Base):
    """
    This is the system's root dispatcher.

    This class ducktypes `BaseCmd`.
    """

    def __init__(self, cfg, run=False, i=None):
        self._run = run
        self.i = i
        self._sender = MsgSender(self)
        self.cfg = cfg
        if not isinstance(cfg["app"], str):
            cfg = cfg["app"]
        self.app = LoadCmd(cfg)
        self.app.attached(self, None)

    async def setup(self):
        await super().setup()
        await AC_use(self, self.app)

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

    def __getattr__(self, k):
        if k[0] == "_":
            return object.__getattr__(self, k)
        return getattr(self.app, k)

    @property
    def root(self) -> RootCmd:
        "root dispatcher"
        return self

    @property
    def sender(self) -> MsgSender:
        "sender adapter"
        return self._sender

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
