import usys

from moat.micro.compat import Event

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
    mn = ".".join(n[:-off if off else 99])
    try:
        res = __import__(mn)
        for nn in n[1:]:
            res = getattr(res,nn)
    except AttributeError as exc:
        raise AttributeError(name) from None
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


### packing

_pkey = 1
_CProxy = {}
_RProxy = {}

def name2obj(name, obj=NotGiven):
    if obj is NotGiven and _CProxy:
        return _CProxy[name]
    _CProxy[name] = obj
    return None

def obj2name(obj, name=NotGiven):
    if name is NotGiven:
        return _RProxy[id(obj)]
    _RProxy[id(obj)] = name
    return None

def _builder(typ, data):
    obj = object.__new__(typ)
    for k,v in data.items():
        setattr(obj,k,v)
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

def _getstate(self):
    return self.__dict__

def as_proxy(name, obj=NotGiven):
    """
    Export an object as a named proxy.
    Usage:

        @as_proxy("foo")
        class Foo():
            def __
        """
    def _proxy(obj):
        "Export @obj as a proxy."
        if name in _CProxy and _CProxy[name] is not obj:
            raise ValueError("Proxy: "+repr(name)+" already exists")
        _CProxy[name] = obj
        _RProxy[id(obj)] = name
#       if isinstance(obj,type) and not hasattr(obj,"__getstate__"):
#           obj.__getstate__ = _getstate
        return obj

    if obj is NotGiven:
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

as_proxy("-")(NotGiven)

