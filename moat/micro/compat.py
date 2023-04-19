import anyio as _anyio

Event = _anyio.Event
Lock = _anyio.Lock
WouldBlock = _anyio.WouldBlock
sleep = _anyio.sleep
import time as _time
import traceback as _traceback

import greenback
import outcome as _outcome
from moat.util import (
    Alert,
    AlertHandler,
    AlertMixin,
    BaseAlert,
    Broadcaster,
    OptCtx,
    Queue,
    RepeatAlert,
    ValueEvent,
)

TimeoutError = TimeoutError  # compat

import logging
from concurrent.futures import CancelledError

logger = logging.getLogger(__name__)

Pin_IN = 0
Pin_OUT = 1


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


async def every_ms(t, p, *a, **k):
    tt = ticks_add(ticks_ms(), t)
    while True:
        try:
            yield await p(*a, **k)
        except StopAsyncIteration:
            return
        tn = ticks_ms()
        td = ticks_diff(tt, tn)
        if td > 0:
            await sleep_ms(td)
            tt += t
        else:
            # owch, delay too long
            tt = ticks_add(tn, t)


def every(t, p, *a, **k):
    return every_ms(t * 1000, p, *a, **k)


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
                # logger.info("Launch %s %s %s %s",_name, p,a,k)

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
    """
    Adapts an anyio stream to MoaT
    """

    def __init__(self, stream):
        self.s = stream
        self.aclose = stream.aclose

    async def recv(self, n=128):
        try:
            res = await self.s.receive(n)
            return res
        except (_anyio.EndOfStream, _anyio.ClosedResourceError):
            raise EOFError from None

    async def send(self, buf):
        try:
            return await self.s.send(buf)
        except (_anyio.EndOfStream, _anyio.ClosedResourceError):
            raise EOFError from None

    async def recvi(self, buf):
        try:
            res = await self.s.receive(len(buf))
        except (_anyio.EndOfStream, _anyio.ClosedResourceError):
            raise EOFError from None
        else:
            buf[: len(res)] = res
            return len(res)
