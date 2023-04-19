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


class OptCtx:
    def __init__(self, obj=None):
        self.obj = obj

    def __enter__(self):
        if self.obj is not None:
            return self.obj.__enter__()
        return self

    def __exit__(self, *tb):
        if self.obj is not None:
            return self.obj.__exit__(*tb)


def print_exc(a, b=usys.stderr):
    usys.print_exception(a, b)


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

        # print("RUN",_name,p,a,k, file=usys.stderr)
        return self.create_task(p(*a, **k))  # , name=_name)

    def start_soon(self, p, *a, _name=None, **k):
        # print("RUN",_name,p,a,k, file=usys.stderr)
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


# partial copy of moat.util.queue


class BroadcastReader:
    value = NotGiven
    loss = 0

    def __init__(self, parent, length):
        self.parent = parent
        if length <= 0:
            raise RuntimeError("Length must be at least one")
        self._q = Queue(length)

    def __aiter__(self):
        return self

    async def __anext__(self):
        # The dance below assures that a last value that's been set
        # before closing is delivered.
        if self.loss > 0:
            n, self.loss = self.loss, 0
            raise LostData(n)

        try:
            return await self._q.get()
        except EndOfStream:
            raise StopAsyncIteration from None

    def __call__(self, value):
        try:
            self._q.put_nowait(value)
        except WouldBlock:
            x = self._q.get_nowait()
            print("Dropped:", repr(x), file=usys.stderr)
            self._q.put_nowait(value)
            self.loss += 1

    def close(self):
        "close this reader, detaching it from its parent"
        self._close()
        self.parent._closed_reader(self)  # pylint: disable=protected-access

    def _close(self):
        self._q.close_writer()
        self._q = None

    async def aclose(self):
        "close this reader, detaching it from its parent"
        self.close()


class Broadcaster:
    _reader = None

    def __init__(self, length=1):
        self.length = length

    def __enter__(self):
        if self._reader is not None:
            raise RuntimeError("already entered")
        self._reader = set()
        return self

    async def __aenter__(self):
        return self.__enter__()

    def __exit__(self, *tb):
        self.close()

    async def __aexit__(self, *tb):
        self.close()

    def _closed_reader(self, reader):
        self._reader.remove(reader)

    def __aiter__(self):
        r = BroadcastReader(self, self.length)
        self._reader.add(r)
        return r.__aiter__()

    def reader(self, length):
        """Create a reader with an explicit queue length"""
        r = BroadcastReader(self, length)
        self._reader.add(r)
        return aiter(r)

    def __call__(self, value):
        for r in self._reader:
            r(value)

    def close(self):
        "Close the broadcaster. No more writing."
        if self._reader is not None:
            for r in self._reader:
                r._close()  # pylint: disable=protected-access
            self._reader = None


class BaseAlert(Exception):
    """Alert, initial OR repeat wrapper"""

    pass  # pylint:disable=unnecessary-pass


class Alert(BaseAlert):
    """
    This is an iteratable alert: it can be iterated for new state, or
    closed when complete.

    The iterator terminates when the condition has passed.

    Intended use: subclass this, distribute using an AlarmHandler mix-in.
    """

    state: list = None
    evt: Event = None

    def __init__(self, *data):
        super().__init__(*data)
        self.evt = Event()
        self.q = Broadcaster()
        self.q.__enter__()
        self.set(data)

    def __aiter__(self):
        return self.q.__aiter__()

    def set(self, *data) -> None:
        """
        Set or update the state of this alert.
        """
        self.q(data)

    def resolve(self) -> None:
        """
        End this alert.
        """
        self.q.close()
        self.evt.set()

    def __await__(self):
        return self.wait().__await__()

    async def wait(self) -> None:
        """
        Wait for the alert to end.
        """
        await self.evt.wait()

    def __del__(self):
        self.q.__exit__(None, None, None)


class RepeatAlert(BaseAlert):
    """
    If an existing alert is re-raised, it is wrapped in a RepeatAlert so as
    to not break the existing alert's traceback and related data.
    """

    def __init__(self, err):
        self.error = err


class AlertHandler:
    """
    Collect open alerts.

    This helper class keeps track of open alerts and lets multiple clients
    receive them.
    """

    def __init__(self):
        self.__alarms = {}
        self.__q = Broadcaster()

    def __enter__(self):
        self.__q.__enter__()
        return self

    async def __aenter__(self):
        self.__q.__enter__()
        return self

    async def __aexit__(self, *tb):
        self.__q.__exit__(*tb)

    def __exit__(self, *tb):
        self.__q.__exit__(*tb)

    def reader(self, length=3):
        """
        Returns an async iterator for new alerts.
        """
        return self.__q.reader(length=length)

    def alerts(self):
        """List open alerts"""
        return self.__alarms.values()

    def alert_(self, cls, *msg) -> Alert:
        """
        Alarm trigger.

        Alarms are static: you can update an alarm with new data.

        To clear an alarm, pass in no data.
        """
        if cls in self.__alarms:
            if msg:
                err = self.__alarms[cls]
                err(*msg)
            else:
                err = self.__alarms.pop(cls)
                err.resolve()
            return err
        elif not msg:
            return None
        err = cls(*msg)
        self.__alarms[cls] = err
        self.__q(err)
        return err

    def raise_(self, cls, *msg):
        """
        Raises this alert as an exception, in addition to queuing it.

        An updated exception will be wrapped in a RepeatAlert.
        """
        # This is a mangled copy of `alert_`.
        if cls in self.__alarms:
            if msg:
                err = self.__alarms[cls]
                err(*msg)
                raise RepeatAlert(err)
            else:
                err = self.__alarms.pop(cls)
                err.close()
                return
        elif not msg:
            return
        err = cls(*msg)
        self.__alarms[cls] = err
        self.__q(err)
        raise err

    def watch_(self, length=3) -> BroadcastReader:
        """
        Monitor for new alerts.
        """
        return self.__q.reader(length)


class AlertMixin:
    """
    Use this mixin to equip your class with alert handling.

    The `AlertHandler` is stored in the ``_alerts`` attribute.
    """

    def __init__(self, *a, **kw):
        self._alerts = AlertHandler()
        super().__init__(*a, **kw)

    def alerts(self, length=3):
        """
        Return an async iterator for new alerts.

        Pass @length to change the maximal queue length (default 3)
        """
        return self._alerts.reader(length)

    def current_alerts(self):
        """
        Return a list of currently-active alerts.

        The result is an iterator. Don't switch tasks while it is active.
        """
        return self._alerts.alerts()

    def set_alert(self, cls, *msg):
        """
        Alert trigger/updater.

        To clear an alert, pass in no data.
        """
        self._alerts.alert_(cls, *msg)

    def raise_alert(self, cls, *msg):
        """
        Raising alert trigger/updater.

        To clear an alert, pass in no data.
        """
        self._alerts.raise_(cls, *msg)


class AlertCollector:
    """
    This context manager stores a variety of alerts, or in fact any other
    object that can be ``await``ed. It is basically the read-side
    counterpart of an `AlertHandler`.

    Awaiting it will delay until all alerts that have been fed to it are
    resolved.

    If the object itself needs to be awaited, or a function other than
    ``wait``, set @access to an appropriate Lambda:

        evtents = AlertController(access=lambda x:x)
    """

    _tg = None
    _working = None

    def __init__(self, access=lambda x: x.wait()):
        self.objs = set()
        self.access = access

        self.non_empty = Event()
        self.evt = Event()
        self.evt.set()

    # if non_empty is not None:
    #    .evt is set
    #    the system is idle.
    # otherwise
    #    .evt is not set
    #    .objs and _working contain the alerts to be waited on.
    #
    # The transition from empty to non-empty is the job of ``.add()``
    # (which doesn't depend on the context to be active).

    def __repr__(self):
        if self.objs or self._working:
            evts = " ".join(self.objs) + " " + str(self._working)
            return f"<{self.__class__.__name__}: {evts}>"
        else:
            return f"<{self.__class__.__name__}: empty>"

    async def wait(self):
        "Wait until all alerts have ben resolved."
        await self.evt.wait()

    def __await__(self):
        return self.evt.wait().__await__()

    async def _runner(self):
        while True:
            if self.objs:
                self._working = w = self.objs.pop()
                try:
                    await self.access(w)
                except BaseException:
                    self.objs.add(w)
                    raise
                finally:
                    self._working = None
            else:
                self.evt.set()
                if self.non_empty is None:
                    self.non_empty = Event()
                await self.non_empty.wait()
                self.non_empty = None

    async def wait_busy(self):
        """
        wait until an alert has been raised.
        """
        if self.non_empty is None:
            return
        await self.non_empty.wait()

    def is_busy(self):
        """
        Check if this collector contains unresolved alerts.

        May be spuriously positive if the internal task is slow, or not
        running.
        """
        return self.non_empty is None

    async def __aenter__(self):
        self._tgm = TaskGroup()
        self._tg = self._tgm.__aenter__()
        return self

    async def __aexit__(self, *tb):
        try:
            await self._tgm.__aexit__()
        finally:
            self._tg = self._tgm = None

    def add(self, thing):
        """Wait for this event."""
        if self.non_empty is not None:
            self.evt = Event()
            self.non_empty.set()
        self.objs.add(thing)
