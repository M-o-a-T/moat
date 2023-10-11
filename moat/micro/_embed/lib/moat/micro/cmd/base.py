"""
Basic infrastructure to run an RPC system via an unreliable,
possibly-reordering, and/or stream-based transport

We have a stack of classes, linked by parent/child pointers.
At the bottom there's some Stream adapter. At the top we have the command
handling, implemented by the classes Request (send a command, wait for
reply) and Base (receive a command, generate a reply). Base classes form
a tree.

Everything is fully asynchronous. Each class has a "run" method which is
required to call its child's "run", as well as do internal housekeeping
if required. A "run" method may expect its parent to be operational;
it gets cancelled if/when that is no longer true. When a child's "run"
terminates, the parent's "run" needs to return.

Incoming messages are handled by the child's "dispatch" method. They
are expected to be fully asynchronous, i.e. a "run" method that calls
"dispatch" must use a separate task to do so.

Outgoing messages are handled by the parent's "send" method. Send calls
return when the data has been sent, implying that sending on an
unreliable transport will wait for the message to be confirmed. Sending
may fail.
"""

from __future__ import annotations

from moat.micro.compat import TaskGroup, idle, Event, wait_for_ms, log, Lock, AC_use, TimeoutError
from moat.util import Path

from .util import run_no_exc, StoppedError

class BaseCmd:
    """
    Request/response handler

    This object accepts (sub)commands.
    """

    tg: TaskGroup = None

    _parent:BaseCmd = None
    _ts = None
    _rl_ok = None  # result of last reload

    def __init__(self, cfg):
        self.cfg = cfg
        self._ready: None|Event|Exception = Event()
        # None: stopped
        # Event: running
        # Exception: dead
        self._stopped = Event()

        self.start_lock = Lock()  # used by my parent
        self.th = None  # task handle, used by the parent

    @property
    def path(self):
        return self._parent.path / self._name

    def send(self, *action, _x_err=(), **kw):  # pylint:disable=arguments-differ
        """
        Send a message, returns a reply.

        Delegates to the root dispatcher
        """
        return self.root.dispatch(action, kw, x_err=_x_err)

    async def send_iter(self, _rep, *action, **kw):
        """
        Send a message, receive an iterated reply.

        The first argument is the delay between replies, in msec.

        Usage::

            async with self.iter(250, "foo","bar", baz=123) as it:
                async for msg in it:
                    ...
        """
        res = await self.root.dispatch(action, kw, rep=_rep)
        await AC_use(self, res.aclose)
        return res

    async def send_nr(self, *action, _x_err=(), **kw):  # pylint:disable=arguments-differ
        """
        Send a possibly-lossy message, does not return a reply.

        Delegates to the root dispatcher
        """
        return await self.root.dispatch(action, kw, wait=False, x_err=_x_err)
        # XXX run in a separate task


    async def run(self):
        """
        Runner for this part of your code.

        By default calls `set_ready`, and `loop`.
        If you override this, you need to do that too.
        """
        self.set_ready()
        await self.loop()

    async def setup(self):
        """
        Async setup for this object.

        By default does nothing.

        If you override this, be aware that the command is not yet marked ready.
        Thus, beware of deadlocks if you depend on the readiness of other objects.
        """
        pass

    async def loop(self):
        """
        Main loop. By default does nothing.
        """
        await idle()

    async def wait_ready(self):
        "delay until ready"
        if not isinstance(self._ready, Event):
            raise self._ready
        try:
            await wait_for_ms(500, self._ready.wait)
        except TimeoutError:
            log("Delay %s!", self.path)
            await self._ready.wait()
            log("Delay %s OK", self.path)
        if not isinstance(self._ready, Event):
            raise self._ready

    cmd__rdy = wait_ready

    def set_ready(self, error=None):
        if self._ready is None:
            raise RuntimeError("dead")
        if not isinstance(self._ready, Event):
            raise RuntimeError("errored", self._ready)
        self._ready.set()


    async def run_sub(self):
        """
        Runs my (and my children's) "run" methods.
        """
        try:
            if self._stopped.is_set():
                self._stopped = Event()

            async with TaskGroup() as self.tg:
                await self.start()

                pass  # wait for started tasks to end
        except BaseException as exc:
            # log("out", err=exc)
            if isinstance(self._ready, Event):
                self._ready.set()
                self._ready = RuntimeError(f"died {repr(exc)}")
            raise
        else:
            if self._ready.is_set():
                self._ready = Event()
        finally:
            self._stopped.set()
            self.th = None

    async def start(self):
        await self.tg.spawn(self.run, _name=f"r_{self.path}")


    # Restarting may or may not work properly on MicroPython

    async def restart(self):
        """
        Tell this module to restart itself.

        DO NOT override this.
        """
        if not isinstance(self._ready, Event):
            raise self._ready
        if self._ready.is_set():
            self._ready = Event()
        self.tg.cancel()
        await self._stopped.wait()

    cmd__rs = restart  # restart command

    async def cmd__rl(self, w=False):  # reload
        await self.reload()

    async def cmd__rlq(self, cl=False):  # query reload
        try:
            return self._rl_ok
        finally:
            if cl:
                self._rl_ok = None

    async def reload(self):
        return False

    def attached(self, parent:BaseDirCmd, name:str):
        if self._parent is not None:
            raise RuntimeError(f"already {'.'.join(self.path)}")
        self._parent = parent
        self._name = name
        self.root = parent.root

    async def stop(self, w=True):
        if not isinstance(self._ready, Event):
            return
        self._ready.set()
        self._ready = StoppedError()
        self.tg.cancel()
        if w:
            await self._stopped.wait()

    cmd__stp = stop

    async def dispatch(
            self, action: list[str], msg: dict, rep:int = None, wait:bool = True, x_err=()
    ):  # pylint:disable=arguments-differ
        """
        Process a message.

        @msg is either a dict (keyword+value for the destination handler)
        or not (single direct argument).

        @action may be a string or an array. The first element of
        the array is used to look up a submodule. Same for the first char
        of a string, if there's no command with that name. An empty-string
        action calls the ``cmd`` method.

        Returns whatever the called command returns/raises, or raises
        AttributeError if no command is found.

        Warning: All incoming commands wait for the subsystem to be ready.
        (This doesn't apply to replies of course.)

        If @rep is >0, this request wants an iterator.

        TODO: remove string dispatch.
        """

        if not action:
            raise RuntimeError("noAction")
        elif len(action) > 1:
            raise ValueError("no chain here", action)
        else:
            p = getattr(self,"cmd_"+action[0])
            
        if not wait:
            if rep:
                raise ValueError("can't rep without wait")
            self.tg.spawn(run_no_exc,p,msg, _name=f"Call:{self.path}/{a or '-'}")
            return

        await self.wait_ready()
        r = p(**msg)
        if hasattr(r, "throw"):  # coroutine
            r = await r
        if rep:
            if hasattr(r, "__aiter__"):  # async iter
                r = r.__aiter__()
            if not hasattr(r,"__anext__"):
                # This is not an iterator
                r = IterWrap(p,(),msg, r)
            if not isinstance(r,_DelayedIter):
                r = DelayedIter(it=r, t=rep)
        else:
            if hasattr(r, "__aiter__"):  # async iter
                raise ValueError("iterator")
        return r

    def send(self, *a, _x_err=(), **k):
        "Sending is forwarded to the root"
        return self.root.dispatch(a, k, x_err=_x_err)


    # globally-available commands

    def cmd__dir(self, h=False):
        """
        Rudimentary introspection. Returns a list of available commands @c and
        submodules @d. j=True if callable directly.
        """
        c = []
        res = dict(c=c)

        for k in dir(self):
            if k.startswith("cmd_") and h == (k[4] == '_'):
                c.append(k[4:])
            elif k == ("_cmd" if h else "cmd"):
                res['j'] = True
        return res


