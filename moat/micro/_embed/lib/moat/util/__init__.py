"""
A hacked-up copy of some parts of `moat.util`.
"""

from __future__ import annotations

from copy import deepcopy
import re

from moat.micro.compat import Event, log

from async_queue import Queue, QueueEmpty, QueueFull  # noqa:F401

_PartRE = re.compile("[^:._]+|_|:|\\.")


def P(s):
    return Path.from_str(s)


class Path(tuple):  # noqa:SLOT001
    """
    somewhat-dummy Path

    half-assed string analysis, somewhat-broken output for non-basics
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

    @classmethod
    def from_str(cls, path):
        """
        Constructor to build a Path from its string representation.
        """
        res = []
        part: None | bool | str = False
        # non-empty string: accept colon-eval or dot (inline)
        # True: require dot or colon-eval (after :t)
        # False: accept only colon-eval (start)
        # None: accept neither (after dot)

        esc: bool = False
        # marks that an escape char has been seen

        eval_: bool | int = False
        # marks whether the current input shall be evaluated;
        # 2=it's a hex number

        pos = 0
        if isinstance(path, (tuple, list)):
            return cls(path)
        if path == ":":
            return cls()

        def add(x):
            nonlocal part
            if not isinstance(part, str):
                part = ""
            try:
                part += x
            except TypeError:
                raise SyntaxError(f"Cannot add {x!r} at {pos}") from None

        def done(new_part):
            nonlocal part
            nonlocal eval_
            if isinstance(part, str):
                if eval_:
                    try:
                        if eval_ == -1:
                            part = bytes.fromhex(part)
                        elif eval_ == -2:
                            part = part.encode("ascii")
                        elif eval_ == -3:
                            part = b64decode(part.encode("ascii"))
                        elif eval_ > 1:
                            part = int(part, eval_)
                        else:
                            raise SyntaxError("Generic eval is not supported: {part !r}")
                    except Exception as exc:
                        raise SyntaxError(f"Cannot eval {part!r} at {pos}") from exc
                    eval_ = False
                res.append(part)
            part = new_part

        def new(x, new_part):
            nonlocal part
            if part is None:
                raise SyntaxError(f"Cannot use {part!r} at {pos}")
            done(new_part)
            res.append(x)

        if path == "":
            raise SyntaxError("The empty string is not a path")

        def err():
            nonlocal path, pos
            raise SyntaxError(f"Cannot parse {path!r} at {pos}")

        for e in _PartRE.findall(path):
            if esc:
                esc = False
                if e in ":.":
                    add(e)
                elif e == "e":
                    new("", True)
                elif e == "t":
                    new(True, True)
                elif e == "f":
                    new(False, True)
                elif e == "n":
                    new(None, True)
                elif e == "_":
                    add(" ")
                elif e[0] == "b":
                    done(None)
                    part = e[1:]
                    eval_ = 2
                elif e[0] == "x":
                    done(None)
                    part = e[1:]
                    eval_ = 16
                elif e[0] == "y":
                    done(None)
                    part = e[1:]
                    eval_ = -1
                elif e[0] == "v":
                    done(None)
                    part = e[1:]
                    eval_ = -2
                elif e[0] == "s":
                    done(None)
                    part = e[1:]
                    eval_ = -3
                else:
                    if part is None:
                        err()
                    done("")
                    add(e)
                    eval_ = True
            else:
                if e == ".":
                    if part is None or part is False:
                        err()
                    done(None)
                    pos += 1
                    continue
                elif e == ":":
                    esc = True
                    pos += 1
                    continue
                elif part is True:
                    raise Err(path, pos)
                else:
                    add(e)
            pos += len(e)
        if esc or part is None:
            err()
        done(None)
        return cls(res)

    def __repr__(self):
        return f"P({str(self)!r})"

    def __truediv__(self, x):
        return Path(self + (x,))

    def __add__(self, x):
        return Path(tuple(self) + x)


class NotGiven:
    """Placeholder value for 'no data' or 'deleted'."""

    def __new__(cls):  # noqa:D102
        return cls

    def __repr__(self):
        return "‹NotGiven›"

    def __str__(self):
        return "NotGiven"


class CancelledError(Exception):
    """
    Not an asyncio-style cancellation
    """


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
                raise AttributeError(k) from None
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
    except Exception as exc:
        log("ERR loading %s: %r", name, exc)
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
    """
    Given a proxy name, return the referred object.

    If @obj is given, associate.
    """
    if obj is NotGiven and _CProxy:
        return _CProxy[name]
    _CProxy[name] = obj
    _RProxy[id(obj)] = name
    return None


def obj2name(obj, name=NotGiven):
    """
    Given a proxied object, return the name referring to it.

    If @name is given, associate.
    """
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
    """
    Given a proxied object, return the name referring to it.

    If unknown, create a new temporary name.
    """
    try:
        return _RProxy[id(obj)]
    except KeyError:
        global _pkey  # noqa:PLW0603
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
    A lock-step buffer.

    Very simple, but works only for one reader and one write.
    """

    def __init__(self):
        self.q = Queue(0)
        self._get = Event()
        self._put = Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        """
        Reads from the buffer.

        Waits for the writer to show up before proceeding.
        """
        self._get.set()
        await self._put.wait()
        s, self.s = self.s, None

        self._put = Event()
        return s

    get = __anext__

    async def put(self, s):
        """
        Write to the buffer.

        Waits for the reader to show up before proceeding.
        """
        await self._get.wait()
        self.s = s
        self._put.set()
        self._get = Event()


class NoProxyError(ValueError):
    "Error for nonexistent proxy values"

    # pylint:disable=unnecessary-pass


class Proxy:
    """
    A proxy object, i.e. a placeholder for things that cannot pass through MsgPack.
    """

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name!r})"

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
            f"{self.__class__.__name__}({self.name!r},"
            + ",".join(repr(x) for x in (self.a, self.k))
            + ")"
        )

    def ref(self):
        """Dereferences the proxy"""
        return name2obj(self.name)


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

    if len(d) == 1 and deep and not isinstance(d[0], dict):
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
        elif not isinstance(v[0], dict):
            for vv in v[1:]:
                assert vv is NotGiven or not isinstance(vv, dict)
            if deep and isinstance(v[0], (list, tuple)):
                res[k] = deepcopy(v[0])
            else:
                res[k] = v[0]
        else:
            res[k] = combine_dict(*v, cls=cls)

    return res


# Merge.


def _merge_dict(d, other, drop=False, replace=True):
    for key, value in other.items():
        if value is NotGiven:
            d.pop(key, None)
        elif key in d:
            d[key] = _merge_one(d[key], value, drop=drop, replace=replace)
        else:
            d[key] = value

    if drop:
        keys = []
        for k in d.keys():
            if k not in other:
                keys.append(k)
        for k in keys:
            del d[k]


def _merge_list(item, value, drop=False, replace=True):
    off = 0
    if isinstance(value, (list, tuple)):
        # two lists
        lim = len(item)
        for i in range(min(lim, len(value))):
            if value[i] is NotGiven:
                item.pop(i - off)
                off += 1
            else:
                item[i - off] = _merge_one(item[i - off], value[i], drop=drop, replace=replace)

        while len(item) + off < len(value):
            val = value[len(item) + off]
            if val is NotGiven:
                off += 1
            else:
                item.append(val)

        if drop:
            while len(item) + off > len(value):
                item.pop()

    else:
        # a list, and a dict with updated/new/deleted values
        for i in range(len(item)):
            if i in value:
                val = value[i]
                if val is NotGiven:
                    item.pop(i - off)
                    off += 1
                else:
                    item[i - off] = _merge_one(item[i - off], val, drop=drop, replace=replace)

        while len(item) + off in value:
            val = value[len(item) + off]
            if val is NotGiven:
                off += 1
            else:
                item.append(val)


def _merge_one(d, other, drop=False, replace=True):
    if isinstance(d, dict):
        if isinstance(other, dict):
            _merge_dict(d, other, drop=drop, replace=replace)
        else:
            return other if replace else d
    elif isinstance(d, list):
        if isinstance(other, (dict, list, tuple)):
            _merge_list(d, other, drop=drop, replace=replace)
        else:
            return other if replace else d
    else:
        if replace:
            return d if other is None else other
        else:
            return other if d is None else d
    return d


def merge(d, *others, drop=False, replace=True):
    """
    Deep-merge a "source" and one or more "replacement" data structures.

    In contrast to `combine_dict`, the source is modified in-place.

    Rules:
    * two dicts: recurse into same-key items, and adds new items
    * two lists: recurse into same-index items
      append to the source if the replacement is longer
    * a list and a dict treats the dict as a sparse list. The value of numeric keys just
      beyond the list's length are appended, others are ignored.
    * a replacement value of `NotGiven` deletes the source entry
    * otherwise, use the second argument if it is not None, otherwise the first
      * except that if "replace" is False, these are swapped

    If "drop" is set, delete source keys that are not in the destination.
    This is useful for in-place replacements.
    """
    for other in others:
        d = _merge_one(d, other, drop=drop, replace=replace)
    return d
