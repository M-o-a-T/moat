import uasyncio
import sys

Event = uasyncio.Event
Lock = uasyncio.Lock
sleep = uasyncio.sleep
sleep_ms = uasyncio.sleep_ms
TimeoutError = uasyncio.TimeoutError
_run = uasyncio.run
_tg = uasyncio.TaskGroup
CancelledError = uasyncio.CancelledError
from uasyncio.queues import Queue, QueueEmpty, QueueFull
from utime import ticks_add, ticks_diff, ticks_ms


class EndOfStream(Exception):
    pass


class BrokenResourceError(Exception):
    pass


try:
    from machine import Pin
except ImportError:  # µPy on Linux
    Pin_IN = "IN"
    Pin_OUT = "OUT"
else:
    Pin_IN = Pin.IN
    Pin_OUT = Pin.OUT

WouldBlock = (QueueFull, QueueEmpty)


def print_exc(a, b=sys.stderr):
    sys.print_exception(a, b)


from moat.util import NotGiven


class LostData(ValueError):
    pass


async def idle():
    while True:
        await sleep(60 * 60 * 12)  # half a day


def wait_for(timeout, p, *a, **k):
    """
    uasyncio.wait_for() but with sane calling convention
    """
    return uasyncio.wait_for(p(*a, **k), timeout)


def wait_for_ms(timeout, p, *a, **k):
    """
    uasyncio.wait_for_ms() but with sane calling convention
    """
    return uasyncio.wait_for_ms(p(*a, **k), timeout)


class _MsecIter:
    tt = None

    def __init__(self, t, p, a, k):
        self.t = t
        self.p, self.a, self.k = p, a, k

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.tt is None:
            self.tt = ticks_add(ticks_ms(), self.t)
        else:
            tn = ticks_ms()
            if (td := ticks_diff(self.tt, tn)) > 0:
                await sleep_ms(td)
                self.tt = ticks_add(self.tt, self.t)
            else:
                # owch, delay too long
                self.tt = ticks_add(tn, self.t)
        return await self.p(*self.a, **self.k)


def every_ms(t, p, *a, **k):
    return _MsecIter(t, p, a, k)


def every(t, p, *a, **k):
    return every_ms(t * 1000, p, *a, **k)


class TaskGroup(_tg):
    async def spawn(self, p, *a, _name=None, **k):
        # returns something you can cancel

        # print("RUN",_name,p,a,k, file=sys.stderr)
        return self.create_task(p(*a, **k))  # , name=_name)

    def start_soon(self, p, *a, _name=None, **k):
        # print("RUN",_name,p,a,k, file=sys.stderr)
        self.create_task(p(*a, **k))


def run(p, *a, **k):
    return _run(p(*a, **k))


async def run_server(*a, **kw):
    from uasyncio import run_server as rs

    return await rs(*a, **kw)


# minimal Outcome clone


class _Outcome:
    def __init__(self, val):
        self.val = val


class _Value(_Outcome):
    def unwrap(self):
        try:
            return self.val
        finally:
            del self.val


class _Error(_Outcome):
    def unwrap(self):
        try:
            raise self.val
        finally:
            del self.val


class ValueEvent:
    # A waitable value useful for inter-task synchronization,
    # inspired by :class:`threading.Event`.

    # An event object manages an internal value, which is initially
    # unset, and a task can wait for it to become True.

    # Note that the value can only be read once.

    def __init__(self):
        self.event = Event()
        self.value = None

    def set(self, value):
        # Set the result to return this value, and wake any waiting task.
        self.value = _Value(value)
        self.event.set()

    def set_error(self, exc):
        # Set the result to raise this exception, and wake any waiting task.
        self.value = _Error(exc)
        self.event.set()

    def is_set(self):
        # Check whether the event has occurred.
        return self.value is not None

    def cancel(self):
        # Send a cancelation to the recipient.
        self.set_error(CancelledError())

    async def get(self):
        # Block until the value is set.

        # If it's already set, then this method returns immediately.

        # The value can only be read once.
        await self.event.wait()
        return self.value.unwrap()
