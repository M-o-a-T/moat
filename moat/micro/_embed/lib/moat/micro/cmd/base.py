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

from moat.lib.cmd.base import MsgHandler
from moat.micro.cmd.util import wait_complain
from moat.micro.cmd.util.part import enc_part, get_part
from moat.micro.proto.stack import Base
from moat.util.compat import AC_use, Event, L, idle

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from moat.util import Path
    from moat.lib.cmd import Msg
    from moat.micro.cmd.tree.dir import BaseSuperCmd, Dispatch

    from collections.abc import Awaitable, Callable


class ACM_h:
    """
    Helper class.

    We want to use "async with disp.send_iter(…)", but send_iter forwards
    to dispatch, which is async, and "async with await …" is cumbersome.

    Thus we use this class to defer resolving the coroutine to the
    __aenter__ call.
    """

    _cm: AbstractAsyncContextManager = None

    def __init__(self, p: Callable, *a, **k):
        self.p = p
        self.a = a
        self.k = k

    async def __aenter__(self):
        self._cm = cm = await self.p(*self.a, **self.k)
        del self.p
        del self.a
        del self.k
        return await cm.__aenter__()

    def __aexit__(self, *tb) -> Awaitable:
        return self._cm.__aexit__(*tb)


class BaseCmd(Base):
    """
    Basic Request handler.

    This class does not accept subcommands.
    """

    root: Dispatch = None
    _parent: BaseSuperCmd = None
    _name: str = None
    _ts = None
    _rl_ok = None  # result of last reload
    p_task = None  # managed by parent. Do not touch.

    if L:
        _starting: Event = None
        _ready: Event = None
    _stopped: Event = None

    def __init__(self, cfg):
        cfg["_cmd"] = self
        super().__init__(cfg)
        # self.cfg = cfg
        self.init_events()

    def init_events(self):
        "Setup events"
        if self._stopped is None:
            if L:
                self._starting = Event()
                self._ready = Event()
            self._stopped = Event()

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.path} {(id(self) >> 4) & 0xFFF:03x}>"

    async def handle(self, msg: Msg, rcmd: list, *prefix: list[str]):
        "See `MsgHandler.handle`."
        ...

    def find_handler(self, path, cmd: bool = False) -> tuple[MsgHandler, Path] | Callable:
        "See `MsgHandler.find_handler`."
        ...

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

        If you need a subtask, override `task`.
        """
        async with self:
            await self.task()

    async def task(self):
        """
        The app's task. Runs after `setup` has completed. By default does nothing.

        If you override this, you're responsible for eventually calling `set_ready`.
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

        doc_rdy_ = dict(_d="check readiness", w="bool:wait for it?")

        def cmd_rdy_(self, w=True) -> Awaitable:
            """
            Check if / wait for readiness.

            See `wait_ready` for return values.
            """
            return self.wait_ready(wait=w)

    async def wait_stopped(self):
        "wait until this is no longer running"
        if self._stopped is not None:
            await self._stopped.wait()

    cmd_stq_ = wait_stopped

    @property
    def path(self):
        "calculate the path to myself"
        # XXX cache it?
        return self._parent.path / self._name

    doc_dir_ = dict(
        _d="directory",
        v="bool:verbose",
        _r=dict(c=["str:commands"], d=["str:modules"], j="bool:callable"),
    )

    async def cmd_dir_(self, v=True):
        """
        Rudimentary introspection. Returns a dict with
        a list of available commands @c,
        iterators @i, and submodules @d.
        j=True if callable directly.

        If @v ("visible") is set (the default),
        this does not return hidden commands.
        """
        c = []
        s = []
        res = {}

        for k in dir(self):
            if v is (k[-1] == "_"):
                continue
            if k.startswith("cmd_"):
                c.append(k[4:])
            elif k.startswith("stream_"):
                s.append(k[7:])
            elif k == "cmd":
                res["C"] = True
            elif k == "stream":
                res["S"] = True
        if c:
            res["c"] = c
        if s:
            res["s"] = s
        return res

    doc_cfg_ = dict(_d="config", _r="parts")

    async def cmd_cfg_(self, p=()):
        """
        Read this item's config.

        Writing is intentionally not supported.
        """
        return enc_part(get_part(self.cfg, p))

    def attached(self, parent: BaseSuperCmd, name: str):
        "Tell this Cmd it's attached under this parent, with this name."
        if self._parent is not None:
            raise RuntimeError(f"already {'.'.join(self.path)}")
        self._parent = parent
        self._name = name
        self.root = parent.root


BaseCmd.handle = MsgHandler.handle
BaseCmd.find_handler = MsgHandler.find_handler
