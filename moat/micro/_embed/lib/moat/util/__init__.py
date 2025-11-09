"""
A hacked-up copy of some parts of `moat.util`.
"""

from __future__ import annotations

from copy import deepcopy

from async_queue import Queue, QueueEmpty, QueueFull  # noqa:F401

from moat.util.compat import Event, log

from .exc import ExpAttrError as ExpAttrError
from .exc import ExpectedError as ExpectedError
from .exc import ExpKeyError as ExpKeyError
from .path import Path


class OutOfData(EOFError):  # noqa: D101
    pass


NotGiven = Ellipsis


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


def to_attrdict(d) -> attrdict:
    """
    Return a hierarchy with all dicts converted to attrdicts.
    """
    if isinstance(d, dict):
        return attrdict((k, to_attrdict(v)) for k, v in d.items())
    if isinstance(d, Path):
        # this is not in the CPython version because there,
        # `Path` is not a subclass of `tuple`
        return d
    if isinstance(d, (tuple, list)):
        return [to_attrdict(v) for v in d]
    return d


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


def exc_iter(exc):
    """
    iterate over all non-exceptiongroup parts of an exception(group)
    """
    from moat.util.compat import BaseExceptionGroup, ExceptionGroup  # noqa: PLC0415,A004

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
        for k in d:
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


def _add_obj(a, b):
    """add attributes of B to A if they're missing"""
    for k in dir(b):
        if not hasattr(a, k):
            setattr(a, k, getattr(b, k))
