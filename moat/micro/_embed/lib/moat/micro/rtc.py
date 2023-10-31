"""
This module manages storing a satellite's volatile part of the MoaT state.

It saves updates to selected config values in RTC memory, or on the Flash
file system if that is not available or dead.

The state behaves like a dict.
"""
from __future__ import annotations

try:
    from machine import RTC
except ImportError:
    RTC = None
from moat.util import merge
from moat.micro.compat import log
from moat.micro.proto.stream import _decode, _encode

import msgpack as mp

_pack = mp.Packer(default=_encode).packb
_unpack = lambda x: mp.unpackb(x, ext_hook=_decode)  # noqa:E731

_dfn = "moat.rtc"


def get_p(cur, p):
    "retrieve an item"
    for pp in p:
        cur = cur[pp]
    return cur


def set_p(cur, p, v):
    "set an item"
    cur = get_p(cur, p[:-1])
    cur[p[-1]] = v


def del_p(cur, p):
    "delete an item"
    pp = p[0]
    if pp in cur:
        if len(p) > 1:
            del_p(cur[pp], p[1:])
        if cur[pp]:
            return
        del cur[pp]


class State:
    """
    Storage for MoaT state.

    This is a singleton object, representing the content of non-volatile
    RAM. MoaT uses it to avoid writing volatile data to Flash file system
    storage.

    Data are represented as a mapping. String keys are global settings.
    Tuples are paths into the configuration: the value updates or replaces
    the static configuration's content at that point.
    """

    def __init__(self):
        self._d = {}
        try:
            r = RTC()
            m = self._m = r.memory
        except (TypeError, AttributeError):
            raise ImportError("No RTC") from None
        else:
            try:
                if m() != b"":
                    self._d = _unpack(m())
                    return
            except Exception as exc:
                log("RTC error", err=exc)

    @property
    def data(self):
        "data directory"
        return self._d

    def update(self, cfg):
        """Given a config, update it with my data"""
        for k, v in self._d.items():
            if isinstance(v, dict):
                merge(cfg.setdefault(k, {}), v)

        return cfg

    def __iter__(self):
        return self._d.items()

    def __getitem__(self, k):
        if isinstance(k, str):
            k = (k,)
        return get_p(self._d, k)

    def __contains__(self, k):
        try:
            self[k]
        except KeyError:
            return False
        else:
            return True

    def __setitem__(self, k, v):
        if isinstance(k, str):
            k = (k,)
        set_p(self._d, k, v)
        self._wr()

    def __delitem__(self, k):
        if isinstance(k, str):
            k = (k,)
        del_p(self._d, k)
        self._wr()

    def _wr(self):
        if self._m is not None:
            self._m(_pack(self._d))


try:
    state = State()
except ImportError:
    state = None
