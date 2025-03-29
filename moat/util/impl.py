"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from contextlib import nullcontext, suppress
from getpass import getpass
from math import log10

__all__ = [
    "NoneType",
    "singleton",
    "TimeOnlyFormatter",
    "count",
    "acount",
    "Cache",
    "NoLock",
    "OptCtx",
    "digits",
    "num2byte",
    "byte2num",
    "split_arg",
    "num2id",
    "import_",
    "load_from_cfg",
]

NoneType = type(None)

NoLock = nullcontext()


class OptCtx:
    """
    Optional context. Unlike `contextlib.nullcontext` this doesn't return a
    fixed value; instead it delegates to the wrapped context manager – if
    there is one.
    """

    def __init__(self, obj=None):
        self.obj = obj

    def __enter__(self):
        if self.obj is not None:
            return self.obj.__enter__()
        return None

    def __exit__(self, *tb):
        if self.obj is not None:
            return self.obj.__exit__(*tb)
        return None

    async def __aenter__(self):
        if self.obj is not None:
            return await self.obj.__aenter__()
        return None

    async def __aexit__(self, *tb):
        if self.obj is not None:
            return await self.obj.__aexit__(*tb)
        return None


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
    except Exception:
        sys.modules.pop(mn, None)
        raise
    return res


def load_from_cfg(*a, _cfg=None, _attr="server", _raise=False, **k):
    """
    A simple frontend to load a module, access a class/object from it,
    and call that with the config (and whchever other arguments you want to
    use).

    The module+object name is the "server" attribute (or @_attr).
    """
    if _cfg is None:
        cfg = k["cfg"]
    try:
        name = cfg[_attr]
    except KeyError:
        if _raise:
            raise
        return None
    if isinstance(name, (list, tuple)):
        name, off = name
    else:
        off = 1
    m = import_(name, off=off)
    return m(*a, **k)


def singleton(cls):
    """Basic singleton decorator"""
    return cls()


class TimeOnlyFormatter(logging.Formatter):
    """A log formatter that doesn't show dates"""

    default_time_format = "%H:%M:%S"
    default_msec_format = "%s.%03d"


def count(it):
    """counts the length of an iterator"""
    n = 0
    for _ in it:
        n += 1
    return n


async def acount(it):
    """counts the length of an async iterator"""
    n = 0
    async for _ in it:
        n += 1
    return n


class Cache:
    """
    A quick-and-dirty cache that keeps the last N entries of anything
    in memory so that ref and WeakValueDictionary don't lose them.

    Entries get refreshed when they're in the last third of the cache; as
    they're not removed, the actual cache size might only be 2/3rd of SIZE.
    """

    def __init__(self, size):
        self._size = size
        self._head = 0
        self._tail = 0
        self._attr = "_cache__pos"
        self._q = deque()

    def keep(self, entry):
        """Store an entry in the cache"""
        if getattr(entry, self._attr, -1) > self._tail + self._size / 3:
            return
        self._head += 1
        setattr(entry, self._attr, self._head)
        self._q.append(entry)
        self._flush()

    def _flush(self):
        while self._head - self._tail > self._size:
            self._q.popleft()
            self._tail += 1

    def resize(self, size):
        """Change the size of this cache."""
        self._size = size
        self._flush()

    def clear(self):
        """Clear the cache"""
        while self._head > self._tail:
            self._q.popleft()
            self._tail += 1


def digits(n, digits=6):  # pylint: disable=redefined-outer-name
    """
    Returns ``n`` rounded to ``digits`` significant digits. Default: 6.
    Ensures that the number doesn't carry nonsense precision or
    floating-point artefacts.

    >>> digits(123456789, 4)
    123400000
    >>> digits(math.pi, 4)
    3.142

    ``digits`` may be a fraction, in order to move the cut-off point to
    somewhere other than between 9.999 and 10.00.
    """
    return round(n, int(digits - 1 - log10(abs(n))))


def num2byte(num: int, length=None):
    """
    convert an unsigned integer to a bytestring
    """
    if length is None:
        length = (num.bit_length() + 7) // 8
    return num.to_bytes(length=length, byteorder="big")


def byte2num(data: bytes):
    """
    convert a bytestring to an unsigned integer
    """
    return int.from_bytes(data, byteorder="big")


def split_arg(p, kw):
    """
    Split argument 'p' and add to dict 'kw'.

    'p' may be of the form x=y (y is added, possibly as an integer),
    x? (call getpass(x? )), x?=y (call getpass(y: )).
    """
    try:
        k, v = p.split("=", 1)
    except ValueError:
        if p[-1] == "?":
            k = p[:-1]
            v = getpass(k + "? ")
        else:
            raise
    else:
        if k[-1] == "?":
            k = k[:-1]
            v = getpass(v + ": ")
        with suppress(ValueError):
            v = int(v)
    kw[k] = v


_alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"


def num2id(number, alphabet=_alphabet):
    """
    Encode a number / object ID in base36 (default).

    This code doesn't care about num2id(739172) or similar.

    To avoid these issues, pass an alphabet without vowels
    as the second parameter. `moat.util.random` contains some
    you might consider useful.
    """
    if not isinstance(number, int):
        if isinstance(number, (float, complex, str, bytes, bytearray)):
            raise TypeError("number must be an object or integer")
        number = id(number)
    is_negative = number < 0
    number = abs(number)
    res = []

    while number:
        number, i = divmod(number, len(alphabet))
        res.append(alphabet[i])
    if is_negative:
        res.append("-")
    elif not res:
        return alphabet[0]
    res.reverse()

    return "".join(res)
