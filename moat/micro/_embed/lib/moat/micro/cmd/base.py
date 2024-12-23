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

from moat.util import as_proxy
from moat.micro.cmd.util import run_no_exc, wait_complain
from moat.micro.cmd.util.part import enc_part, get_part
from moat.micro.compat import AC_use, Event, L, idle
from moat.micro.errors import NoPathError
from moat.micro.proto.stack import Base

if L:
    from .util.iter import DelayedIter, IterWrap

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import AsyncContextManager
    from collections.abc import AsyncIterator, Awaitable, Callable

    from moat.micro.cmd.tree.dir import BaseSuperCmd, Dispatch


as_proxy("_SCmdErr")


class ShortCommandError(ValueError):
    "The command path was too short"

    pass


as_proxy("_LCmdErr")


class LongCommandError(ValueError):
    "The command path was too long"

    pass


class ACM_h:
    """
    Helper class.

    We want to use "async with disp.send_iter(…)", but send_iter forwards
    to dispatch, which is async, and "async with await …" is cumbersome.

    Thus we use this class to defer resolving the coroutine to the
    __aenter__ call.
    """

    _cm: AsyncContextManager = None

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
    Basic Request/response handler.

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

    def send(self, *action, _x_err=(), **kw) -> Awaitable:
        """
        Send a message, returns a reply.

        Delegates to the root dispatcher.

        Do not override this.
        """
        return self.root.dispatch(action, kw, x_err=_x_err)

    def send_iter(self, _rep, *action, **kw) -> AsyncContextManager:
        """
        Send a message, receive an iterated reply.

        The first argument is the delay between replies, in msec.

        Usage::

            async with self.iter(250, "foo","bar", baz=123) as it:
                async for msg in it:
                    ...

        Delegates to the root dispatcher, using a wrapper so the caller
        doesn't need to write ``async with await self.iter(…)``.

        Do not override this.
        """
        return ACM_h(self.root.dispatch, action, kw, rep=_rep)

    def send_nr(self, *action, _x_err=(), **kw) -> Awaitable:
        """
        Send a possibly-lossy message, does not return a reply.

        Delegates to the root dispatcher

        Do not override this.
        """
        return self.root.dispatch(action, kw, wait=False, x_err=_x_err)
        # XXX run in a separate task

    async def dispatch(
        self,
        action: list[str],
        msg: dict,
        *,
        rep: int | None = None,
        wait: bool = True,
        x_err=(),
    ) -> Awaitable | AsyncContextManager[AsyncIterator]:  # pylint:disable=arguments-differ
        """
        Process a message.

        @msg is either a dict (keyword+value for the destination handler)
        or not (single direct argument).

        @action is a list. This dispatcher requires it to have exactly one
        element: the command name.

        Returns whatever the called command returns/raises, or raises
        AttributeError if no command is found.

        Warning: All incoming commands wait for the subsystem to be ready.

        If @rep is >0, the requestor wants an async context manager that
        yields/implements an iterator with (roughly) @rep milliseconds between
        values. If no `iter_‹name›` method exists, `cmd_‹name›` will be
        called repeatedly.
        """

        if not action:
            raise ShortCommandError(())
        if len(action) > 1:
            raise LongCommandError(action)

        a = action[0]
        if a[0] == "?":
            wr = False
            fn = a[1:]
        else:
            wr = True
            fn = a

        if rep is not None:
            if not L:
                raise RuntimeError("not Large")
            if not wait:
                raise ValueError("can't rep without wait")
            try:
                p = getattr(self, f"iter_{fn}")
            except AttributeError:
                p = getattr(self, f"cmd_{fn}")
                r = IterWrap(p, (), msg)
            else:
                r = p(**msg)
                if hasattr(r, "throw"):  # coroutine
                    raise TypeError("iter is async")
            return DelayedIter(it=r, t=rep)

        try:
            p = getattr(self, f"cmd_{fn}")
        except AttributeError:
            raise NoPathError(
                self.path,
                (fn,),
                self.__class__.__name__,
                await self.cmd_dir_(v=None),
            ) from None

        if not wait:
            # XXX better idea without forcing a taskgroup on everything?
            tg = getattr(self, "tg", self.root.tg)
            tg.spawn(run_no_exc, p, msg, x_err, _name=f"Call:{self.path}/{p}")
            return

        if L and wr:
            await self.wait_ready()
        r = await p(**msg)
        return r

    # globally-available commands

    async def cmd_dir_(self, v=True):
        """
        Rudimentary introspection. Returns a dict with
        a list of available commands @c,
        iterators @i, and submodules @d.
        j=True if callable directly.

        If @v is set (the default), don't return hidden commands.
        """
        c = []
        i = []
        res = {}

        for k in dir(self):
            if v is (k[-1] == "_"):
                continue
            if k.startswith("cmd_"):
                c.append(k[4:])
            elif k.startswith("iter_"):
                i.append(k[5:])
            elif k == "cmd":
                res["j"] = True
            elif k == "cmd_":
                res["J"] = True
        if c:
            res["c"] = c
        if i:
            res["i"] = i
        return res

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
