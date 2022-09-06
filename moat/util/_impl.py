"""
This module contains various helper functions and classes.
"""
import logging
from collections import deque
from getpass import getpass
from math import log10

__all__ = [
    "NoneType",
    "singleton",
    "TimeOnlyFormatter",
    "NotGiven",
    "count",
    "acount",
    "Cache",
    "NoLock",
    "digits",
    "num2byte",
    "byte2num",
    "split_arg",
]

NoneType = type(None)


def singleton(cls):
    return cls()


class TimeOnlyFormatter(logging.Formatter):
    default_time_format = "%H:%M:%S"
    default_msec_format = "%s.%03d"


class NotGiven:
    """Placeholder value for 'no data' or 'deleted'."""

    def __new__(cls):
        return cls

    def __getstate__(self):
        raise ValueError("You may not serialize this object")

    def __repr__(self):
        return "‹NotGiven›"

    def __str__(self):
        return "NotGiven"


def count(it):
    n = 0
    for _ in it:
        n += 1
    return n


async def acount(it):
    n = 0
    async for _ in it:  # noqa: F841
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
        while self._head > self._tail:
            self._q.popleft()
            self._tail += 1


@singleton
class NoLock:
    """A dummy singleton that can replace a lock.

    Usage::

        with NoLock if _locked else self._lock:
            pass
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        return


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
    if length is None:
        length = (num.bit_length() + 7) // 8
    return num.to_bytes(length=length, byteorder="big")


def byte2num(data: bytes):
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
        try:
            v = int(v)
        except ValueError:
            pass
    kw[k] = v
