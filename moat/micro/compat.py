import anyio as _anyio

Event = _anyio.Event
Lock = _anyio.Lock
WouldBlock = _anyio.WouldBlock
sleep = _anyio.sleep
import time as _time
import traceback as _traceback

import greenback
import outcome as _outcome
from moat.util import Queue, ValueEvent

TimeoutError = TimeoutError  # compat

from concurrent.futures import CancelledError


def print_exc(exc):
    _traceback.print_exception(type(exc), exc, exc.__traceback__)


def ticks_ms():
    return _time.monotonic_ns() // 1000000


async def sleep_ms(ms):
    await sleep(ms / 1000)


async def wait_for(timeout, p, *a, **k):
    with _anyio.fail_after(timeout):
        return await p(*a, **k)


async def wait_for_ms(timeout, p, *a, **k):
    with _anyio.fail_after(timeout / 1000):
        return await p(*a, **k)


async def idle():
    while True:
        await anyio.sleep(60 * 60 * 12)  # half a day


def ticks_add(a, b):
    return a + b


def ticks_diff(a, b):
    return a - b


from concurrent.futures import CancelledError as _Cancelled

import attr as _attr

try:
    _d_a = _anyio.DeprecatedAwaitable
except AttributeError:  # no back compat
    _d_a = lambda _: None


@_attr.s
class ValueEvent:
    """A waitable value useful for inter-task synchronization,
    inspired by :class:`threading.Event`.

    An event object manages an internal value, which is initially
    unset, and a task can wait for it to become True.

    Args:
      ``scope``:  A cancelation scope that will be cancelled if/when
                  this ValueEvent is. Used for clean cancel propagation.

    Note that the value can only be read once.
    """

    event = _attr.ib(factory=Event, init=False)
    value = _attr.ib(default=None, init=False)
    scope = _attr.ib(default=None, init=True)

    def set(self, value):
        """Set the result to return this value, and wake any waiting task."""
        self.value = _outcome.Value(value)
        self.event.set()
        return _d_a(self.set)

    def set_error(self, exc):
        """Set the result to raise this exceptio, and wake any waiting task."""
        self.value = _outcome.Error(exc)
        self.event.set()
        return _d_a(self.set_error)

    def is_set(self):
        """Check whether the event has occurred."""
        return self.value is not None

    def cancel(self):
        """Send a cancelation to the recipient.

        TODO: Trio can't do that cleanly.
        """
        if self.scope is not None:
            self.scope.cancel()
        self.set_error(_Cancelled())
        return _d_a(self.cancel)

    async def get(self):
        """Block until the value is set.

        If it's already set, then this method returns immediately.

        The value can only be read once.
        """
        await self.event.wait()
        return self.value.unwrap()


_tg = None


async def _run(p, a, k):
    global _tg
    async with _anyio.create_task_group() as _tg:
        try:
            return await p(*a, **k)
        finally:
            _tg.cancel_scope.cancel()
            _tg = None


def run(p, *a, **k):
    return _anyio.run(_run, p, a, k)


_tg = None


def TaskGroup():
    global _tg
    if _tg is None:
        _tgt = type(_anyio.create_task_group())

        class TaskGroup(_tgt):
            """An augmented taskgroup"""

            async def spawn(self, p, *a, _name=None, **k):
                """\
                    Like start(), but returns something you can cancel
                """

                async def catch(p, a, k, *, task_status):
                    with _anyio.CancelScope() as s:
                        task_status.started(s)
                        await greenback.ensure_portal()
                        try:
                            await p(*a, **k)
                        except CancelledError:  # error from concurrent.futures
                            pass

                return await super().start(catch, p, a, k, name=_name)

            def cancel(self):
                self.cancel_scope.cancel()

        _tg = TaskGroup
    return _tg()


async def run_server(cb, host, port, backlog=5, taskgroup=None, reuse_port=True):
    listener = await anyio.create_tcp_listener(
        local_host=host, local_port=port, backlog=backlog, reuse_port=reuse_port
    )

    async def cbc(sock):
        await cb(sock, sock)

    await listener.serve(cbc, task_group=taskgroup)


class AnyioMoatStream:
    # adapt an anyio stream to our scheme.
    def __init__(self, stream):
        self.s = stream
        self.aclose = stream.aclose

    async def recv(self, n=128):
        try:
            res = await self.s.receive(n)
            return res
        except _anyio.EndOfStream:
            raise EOFError from None

    async def send(self, buf):
        return await self.s.send(buf)

    async def recvi(self, buf):
        res = self.s.receive(len(buf))
        buf[:] = res
        return res
