import uasyncio
import usys

Event = uasyncio.Event
Lock = uasyncio.Lock
sleep = uasyncio.sleep
sleep_ms = uasyncio.sleep_ms
TimeoutError = uasyncio.TimeoutError
_run = uasyncio.run
_tg = uasyncio.TaskGroup
CancelledError = uasyncio.CancelledError
# from uasyncio import Event,Lock,sleep,sleep_ms,TimeoutError, run as _run, TaskGroup as _tg, CancelledError
from uasyncio.queues import Queue, QueueEmpty, QueueFull
from utime import ticks_add, ticks_diff, ticks_ms

WouldBlock = (QueueFull, QueueEmpty)


def print_exc(a, b=usys.stderr):
    usys.print_exception(a, b)


async def idle():
    while True:
        await sleep(60 * 60 * 12)  # half a day


async def wait_for(timeout, p, *a, **k):
    """
    uasyncio.wait_for() but with sane calling convention
    """
    return await uasyncio.wait_for(p(*a, **k), timeout)


async def wait_for_ms(timeout, p, *a, **k):
    """
    uasyncio.wait_for_ms() but with sane calling convention
    """
    return await uasyncio.wait_for_ms(p(*a, **k), timeout)


class TaskGroup(_tg):
    async def spawn(self, p, *a, _name=None, **k):
        return self.create_task(p(*a, **k))  # , name=_name)


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
