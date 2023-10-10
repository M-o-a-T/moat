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

from .util import run_no_exc

class BaseCmd:
    """
    Request/response handler

    This object accepts (sub)commands.
    """

    _tg: TaskGroup = None
    _starting = None
    _parent:BaseCmd = None
    _ts = None
    _start_lock = Lock()

    def __init__(self, cfg):
        self._sub = {}
        self.cfg = cfg
        self._ready: None|Event|Exception = Event()
        # None: stopped
        # Event: running
        # Exception: died
        self._stopped = Event()
        self._restart = True

    @property
    def path(self):
        return self._parent.path / self._name

    async def send(self, *action, **kw):  # pylint:disable=arguments-differ
        """
        Send a message, returns a reply.

        Delegates to the root dispatcher
        """
        return await self.root.dispatch(action, kw)

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

    async def send_nr(self, *action, **kw):  # pylint:disable=arguments-differ
        """
        Send a possibly-lossy message, does not return a reply.

        Delegates to the root dispatcher
        """
        return await self.root.dispatch(action, kw, wait=False)
        # XXX run in a separate task


    async def run(self):
        """
        Runner for this part of your code.

        By default calls `setup`, `set_ready`, and `loop`.
        You need to do all of that if you override `run`.
        """
        await self.setup()
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

    cmd_rdy = wait_ready

    async def wait_all_ready(self):
        "delay until this subtree is up"
        await self.wait_ready()
        while True:
            n = len(self._sub)
            for k,v in list(self._sub.items()):
                await v.wait_all_ready()
                # TODO warn when delayed
            if len(self._sub) == n:
                break

    def set_ready(self, error=None):
        if self._ready is None:
            raise RuntimeError("dead")
        if not isinstance(self._ready, Event):
            raise RuntimeError("errored", self._ready)
        self._ready.set()


    async def _run(self):
        """
        Runs my (and my children's) "run" methods.
        """
        while isinstance(self._ready, Event):
            try:
                if self._stopped.is_set():
                    self._stopped = Event()
                async with TaskGroup() as tg:
                    self._tg = tg
                    await tg.spawn(self.run, _name=f"r_{self.path}")
                    await self._start()

                    # Subprogram config is either in init or at runtime.
                    await self.wait_ready()
                    self._starting = False
            except Exception as exc:
                # log("out", err=exc)
                if isinstance(self._ready, Event):
                    self._ready.set()
                    self._ready = RuntimeError("died")
                raise
            else:
                if self._ready.is_set():
                    self._ready = Event()
            finally:
                self._stopped.set()

    async def _start(self):
        self._starting = True
        for k,v in self._sub.items():
            if isinstance(v, BaseCmd):
                async with v._start_lock:
                    if v._ts is None:
                        log("Startup %s",self.path/k)
                        v._ts = await self._tg.spawn(v._run_, _name=f"r_st_{v.path}")

    async def _run_(self):
        try:
            await self._run()
        finally:
            self._ts = None


    # Restarting may or may not work properly on MicroPython

    async def restart(self):
        """
        Tell this module to restart itself.
        """
        self._tg.cancel()

    def attached(self, parent:BaseDirCmd, name:str):
        if self._parent is not None:
            raise RuntimeError(f"already {'.'.join(self.path)}")
        self._parent = parent
        self._name = name
        self.root = parent.root

    async def stop(self):
        if not isinstance(self._ready, Event):
            return
        self._ready.set()
        self._ready = StoppedError()
        self._tg.cancel()
        await self._stopped.wait()
        if self._parent is not self:
            self._parent = None
            self._name = None
            self.root = None

    async def attach(self, name, cmd, run=True):
        """
        Attach a named command handler to me and run it.
        """
        await self.detach(name)
        self._sub[name] = cmd
        cmd.attached(self, name)
        if run:
            await self._tg.spawn(cmd._run, _name=f"r_at_{cmd.path}")

    async def detach(self, name):
        """
        Detach a named command handler from me and kill its task.

        Waits for the subtask to end.
        """
        try:
            cmd = self._sub.pop(name)
        except KeyError:
            return
        try:
            await cmd.stop()
        except AttributeError:
            pass


    async def dispatch(
            self, action: str | list[str], msg: dict, rep:int = None, wait:bool = True,
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
        """

        async def c(p,a):
            if not wait:
                if rep:
                    raise ValueError("can't rep without wait")
                self._tg.spawn(run_no_exc,p,msg, _name=f"Call:{self.path}/{a or '-'}")
                return

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


        if not action:
            # pylint: disable=no-member
            await self.wait_ready()
            return await c(self.__aiter__ if rep else self.cmd, None)
            # if there's no iterator/cmd, the resulting AttributeError is our reply

        if not isinstance(action, str) and len(action) == 1:
            action = action[0]
        if isinstance(action, str):
#           if rep:
#               # TODO XXX do we need separate iter_* methods?
#               try:
#                   p = getattr(self, "iter_"+action)
#               except AttributeError:
#                   pass
#               else:
#                   await self.wait_ready()
#                   return await c(p)
            try:
                p = getattr(self, "cmd_" + action)
            except AttributeError:
                pass
            else:
                await self.wait_ready()
                return await c(p,action)

        try:
            sub = self._sub[action[0]]
        except KeyError:
            raise AttributeError(action) from None
        else:
            return await sub.dispatch(action[1:], msg, wait=wait, rep=rep)

    def send(self, *a, **k):
        "Sending is forwarded to the root"
        return self.root.dispatch(a, k)


    # globally-available commands

    def cmd__dir(self):
        """
        Rudimentary introspection. Returns a list of available commands @c and
        submodules @d. j=True if callable directly.
        """
        c = []
        d = list(self._sub.keys())
        res = dict(c=c, d=d)

        for k in dir(self):
            if k.startswith("cmd_") and k[4] != '_':
                c.append(k[4:])
            elif k == "cmd":
                res['j'] = True
        return res


