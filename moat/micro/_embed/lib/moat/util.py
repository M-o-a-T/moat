import sys

from async_queue import Queue, QueueEmpty, QueueFull

from moat.micro.compat import Event, WouldBlock, log


class Path(tuple):
    """
    somewhat-dummy Path

    no string analysis, somewhat-broken output for non-basics
    """

    def __str__(self):
        def _escol(x):
            x = x.replace(":", "::").replace(".", ":.").replace(" ", ":_")
            return x

        res = []
        if not len(self):
            res.append(":")
        for x in self:
            if isinstance(x, str):
                if x == "":
                    res.append(":e")
                else:
                    if res:
                        res.append(".")
                    res.append(_escol(x))
            elif x is True:
                res.append(":t")
            elif x is False:
                res.append(":f")
            elif x is None:
                res.append(":n")
            elif isinstance(x, (bytes, bytearray, memoryview)):
                if all(32 <= b < 127 for b in x):
                    res.append(":v" + _escol(x.decode("ascii")))
                else:
                    from base64 import b64encode

                    res.append(":s" + b64encode(x).decode("ascii"))
                    # no hex
            else:
                res.append(":" + _escol(repr(x)))
        return "".join(res)

    def __repr__(self):
        return f"P({repr(str(self))})"

    def __truediv__(self, x):
        return Path(self + (x,))

    def __add__(self, x):
        return Path(tuple(self) + x)


class NotGiven:
    """Placeholder value for 'no data' or 'deleted'."""

    def __new__(cls):
        return cls

    def __repr__(self):
        return "‹NotGiven›"

    def __str__(self):
        return "NotGiven"


class NoProxyError(ValueError):
    pass


class CancelledError(Exception):
    """
    Not an asyncio-style cancellation
    """

    pass


class OptCtx:
    "optional context"

    def __init__(self, obj=None):
        self.obj = obj

    def __enter__(self):
        if self.obj is not None:
            return self.obj.__enter__()
        return self

    def __exit__(self, *tb):
        if self.obj is not None:
            return self.obj.__exit__(*tb)


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

    event = None
    value = None

    def __init__(self, scope=None):
        self.event = Event()
        self.scope = scope

    def set(self, value):
        """Set the result to return this value, and wake any waiting task."""
        self.value = value
        self.event.set()

    def set_error(self, exc):
        """Set the result to raise this exceptio, and wake any waiting task."""
        if isinstance(exc, type):
            exc = exc()
        self.value = exc
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

    async def wait(self):
        """Block until the value is set.

        If it's already set, then this method returns immediately.

        The value is not (yet) read; if it's an error, it will not be raised from here.
        """
        await self.event.wait()

    async def get(self):
        """Block until the value is set.

        If it's already set, then this method returns immediately.

        The value can only be read once.
        """
        await self.event.wait()
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class attrdict(dict):
    """
    A dict that can be accessed via attribute syntax.

    This is a very minimal implementation.
    """

    def __getattr__(self, k, d=NotGiven):
        try:
            return self[k]
        except KeyError:
            if d is NotGiven:
                raise AttributeError(k)
            return d

    def __setattr__(self, k, v):
        self[k] = v

    def __delattr__(self, k):
        try:
            del self[k]
        except KeyError:
            return AttributeError(k)


def import_(name, off=0):
    """
    Import a module and access an object in it.

    `import_("a.b.c.d.e", 2)` imports "a.b.c" and returns the e attribute
    of object d from it.
    """
    n = name.split(".")
    mn = ".".join(n[: -off if off else 99])
    try:
        res = __import__(mn)
        for nn in n[1:]:
            res = getattr(res, nn)
    except AttributeError as exc:
        log("ERR loading %s", name)
        raise
    return res


def load_from_cfg(cfg, *a, _raise=False, **k):
    """
    A simple frontend to load a module, access a class/object from it,
    and call that with the config (and whichever other arguments you want to
    use).

    The module+object name is the "client" attribute.
    """
    if "client" not in cfg:
        if _raise:
            raise ValueError("must be configured")
        return None
    m = import_(cfg.client, off=1)
    return m(cfg, *a, **k)


# packing

_pkey = 1
_CProxy = {}
_RProxy = {}


def name2obj(name, obj=NotGiven):
    if obj is NotGiven and _CProxy:
        return _CProxy[name]
    _CProxy[name] = obj
    _RProxy[id(obj)] = name
    return None


def obj2name(obj, name=NotGiven):
    if name is NotGiven:
        return _RProxy[id(obj)]
    _RProxy[id(obj)] = name
    _CProxy[name] = obj
    return None


def _builder(typ, data):
    obj = object.__new__(typ)
    for k, v in data.items():
        setattr(obj, k, v)
    return obj


def get_proxy(obj):
    try:
        return _RProxy[id(obj)]
    except KeyError:
        global _pkey
        k = "p_" + str(_pkey)
        _pkey += 1
        _CProxy[k] = obj
        _RProxy[id(obj)] = k
        return k


# def _getstate(self):
#     return (type(self), (), self.__dict__)


def as_proxy(name, obj=NotGiven, replace=False):
    """
    Export an object as a named proxy.
    Usage:

        @as_proxy("foo")
        class Foo():
            def __
    """

    def _proxy(obj):
        "Export @obj as a proxy."
        if not replace and name in _CProxy and _CProxy[name] is not obj:
            raise ValueError("Proxy: " + repr(name) + " already exists")
        _CProxy[name] = obj
        _RProxy[id(obj)] = name
        #       if isinstance(obj,type) and not hasattr(obj,"__getstate__"):
        #           obj.__getstate__ = _getstate
        return obj

    if obj is NotGiven and not replace:
        return _proxy
    else:
        _proxy(obj)
        return obj


def drop_proxy(p):
    """
    After sending a proxy we keep it in memory in case the remote returns
    it, or an expression with it.

    If that won't happen, the remote needs to tell us to clean it up.
    """
    if not isinstance(p, str):
        p = _RProxy[id(p)]
    r = _CProxy.pop(p)
    del _RProxy[id(r)]


class Lockstep:
    """
    A lock-step buffer. Very simple, but works only for one reader and one write.
    """

    def __init__(self):
        self.q = q
        self._get = Event()
        self._put = Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        # reader. Signal we're reading, then wait for the item
        self._get.set()
        await self._put.wait()
        self.s = None

        self._put = Event()
        return s

    get = __anext__

    async def put(s):
        await self._get.wait()
        self.s = s
        self._put.set()
        self._get = Event()


class NoProxyError(ValueError):
    "Error for nonexistent proxy values"
    pass  # pylint:disable=unnecessary-pass


class Proxy:
    """
    A proxy object, i.e. a placeholder for things that cannot pass through MsgPack.
    """

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self.name)})"

    def ref(self):
        """Dereferences the proxy"""
        return name2obj(self.name)


class DProxy(Proxy):
    """
    A proxy object of a class to which the reciipient doesn't have a type.
    """

    def __init__(self, name, *a, **k):
        super().__init__(name)
        self.a = a
        self.k = k

    def __getitem__(self, i):
        if i in self.k:
            return self.k[i]
        else:
            return self.a[i]

    def __repr__(self):
        return (
            f"{self.__class__.__name__}({repr(self.name)},"
            + ",".join(repr(x) for x in (self.a, self.k))
            + ")"
        )

    def ref(self):
        """Dereferences the proxy"""
        return name2obj(self.name)


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


def exc_iter(exc):
    """
    iterate over all non-exceptiongroup parts of an exception(group)
    """
    from moat.micro.compat import BaseExceptionGroup, ExceptionGroup

    if isinstance(exc, (ExceptionGroup, BaseExceptionGroup)):
        for e in exc.exceptions:
            yield from exc_iter(e)
    else:
        yield exc


def combine_dict(*d, cls=dict, deep=False) -> dict:
    """
    Returns a dict with all keys+values of all dict arguments.
    The first found value wins.

    This operation is recursive and non-destructive. If `deep` is set, the
    result always is a deep copy.

    A value of `NotGiven` causes an entry to be skipped.

    TODO: arrays are not merged.

    Args:
      cls (type): a class to instantiate the result with. Default: dict.
        Often used: :class:`attrdict`.
      deep (bool): if set, always copy.
    """
    res = cls()
    keys = {}
    if not d:
        return res

    if len(d) == 1 and deep and not isinstance(d[0], Mapping):
        if deep and isinstance(d[0], (list, tuple)):
            return deepcopy(d[0])
        else:
            return d[0]

    for kv in d:
        if kv is None:
            continue
        for k, v in kv.items():
            if k not in keys:
                keys[k] = []
            keys[k].append(v)

    for k, v in keys.items():
        if v[0] is NotGiven:
            pass
        elif len(v) == 1 and not deep:
            res[k] = v[0]
        elif not isinstance(v[0], Mapping):
            for vv in v[1:]:
                assert vv is NotGiven or not isinstance(vv, Mapping)
            if deep and isinstance(v[0], (list, tuple)):
                res[k] = deepcopy(v[0])
            else:
                res[k] = v[0]
        else:
            res[k] = combine_dict(*v, cls=cls)

    return res
