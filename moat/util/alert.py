"""
Implements an alert object and dispatcher.

Alerts are exceptions that can be iterated or waited on.

Waiting will succeed when the alarm is resolved/closed.
Iterating will receive new state and end when the alert is resolved.

The dispatcher is a context manager that can be iterated to receive new
alerts.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from .broadcast import Broadcaster, BroadcastReader
from .compat import Event, TaskGroup
from .ctx import CtxObj

__all__ = [
    "Alert",
    "BaseAlert",
    "RepeatAlert",
    "AlertHandler",
    "AlertMixin",
    "AlertCollector",
]


class BaseAlert(Exception):
    """Alert, initial OR repeat wrapper"""

    # pylint:disable=unnecessary-pass


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


class AlertCollector(CtxObj):
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

    @asynccontextmanager
    async def _ctx(self):
        async with TaskGroup() as self._tg:
            self._tg.start_soon(self._runner)
            yield self
            self._tg.cancel_scope.cancel()

    def add(self, thing):
        """Wait for this event."""
        if self.non_empty is not None:
            self.evt = Event()
            self.non_empty.set()
        self.objs.add(thing)
