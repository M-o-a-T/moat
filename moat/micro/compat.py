import anyio as _anyio
Event = _anyio.Event
sleep = _anyio.sleep

import time as _time
import traceback as _traceback
import outcome as _outcome

from concurrent.futures import CancelledError

def print_exc(exc):
    _traceback.print_exception(type(exc),exc,exc.__traceback__)

def ticks_ms():
    return _time.monotonic_ns() // 1000000

async def wait_for_ms(timeout,p,*a,**k):
    with _anyio.fail_after(timeout/1000):
        return await p(*a,**k)

def ticks_add(a,b):
    return a+b

def ticks_diff(a,b):
    return a-b

from concurrent.futures import CancelledError as _Cancelled

import attr as _attr

try:
    _d_a = _anyio.DeprecatedAwaitable
except AttributeError: # no back compat
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

async def _run(p,a,k):
    global _tg
    async with _anyio.create_task_group() as _tg:
        try:
            return await p(*a,**k)
        finally:
            _tg.cancel_scope.cancel()
            _tg = None

def run(p,*a,**k):
    return _anyio.run(_run,p,a,k)

async def spawn(evt, p,*a,**k):
    """\
        Like anyio.start(), except
        * sets the event if the task ends, if given
        * returns something you can cancel
    """
    async def catch(p,a,k, *, task_status):
        with _anyio.CancelScope() as s:
            task_status.started(s)
            try:
                await p(*a,**k)
            except CancelledError: # error from concurrent.futures
                pass
            finally:
                if evt is not None:
                    evt.set()

    return await _tg.start(catch,p,a,k)

