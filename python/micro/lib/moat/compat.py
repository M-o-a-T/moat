from usys import print_exception as print_exc
import uasyncio
from uasyncio import Event,Lock,sleep,sleep_ms,TimeoutError, run as _run, TaskGroup as _tg, CancelledError
from asyncio.queues import Queue
from utime import ticks_ms, ticks_add, ticks_diff
import attr
import outcome


async def idle():
    while True:
        await sleep(60*60*12)  # half a day

async def wait_for(timeout,p,*a,**k):
    """
        uasyncio.wait_for() but with sane calling convention
    """
    return await uasyncio.wait_for(p(*a,**k),timeout)

async def wait_for_ms(timeout,p,*a,**k):
    """
        uasyncio.wait_for_ms() but with sane calling convention
    """
    return await uasyncio.wait_for_ms(p(*a,**k),timeout)

class TaskGroup(_tg):
    async def spawn(self, p, *a, **k):
        return self.create_task(p(*a,**k))

def run(p,*a,**k):
    return _run(p(*a,**k))

async def run_server(*a, **kw):
    from uasyncio import run_server as rs
    return await rs(*a,**kw)


@attr.s
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

    event = attr.ib(factory=Event, init=False)
    value = attr.ib(default=None, init=False)
    scope = attr.ib(default=None, init=True)

    def set(self, value):
        """Set the result to return this value, and wake any waiting task."""
        self.value = outcome.Value(value)
        self.event.set()

    def set_error(self, exc):
        """Set the result to raise this exceptio, and wake any waiting task."""
        self.value = outcome.Error(exc)
        self.event.set()

    def is_set(self):
        """Check whether the event has occurred."""
        return self.value is not None

    def cancel(self):
        """Send a cancelation to the recipient.

        TODO: Trio can't do that cleanly.
        """
        if self.scope is not None:
            self.scope.cancel()
        self.set_error(CancelledError())

    async def get(self):
        """Block until the value is set.

        If it's already set, then this method returns immediately.

        The value can only be read once.
        """
        await self.event.wait()
        return self.value.unwrap()
