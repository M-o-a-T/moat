"""
This module contains proxy helpers.
"""

from __future__ import annotations

from inspect import isfunction

__all__ = [
    "DProxy",
    "NoProxyError",
    "Proxy",
    "as_proxy",
    "drop_proxy",
    "get_proxy",
    "name2obj",
    "obj2name",
]

from anyio import Path as AioPath
from pathlib import Path as FSPath

from moat.lib.codec._proxy import DProxy as _DProxy
from moat.lib.codec._proxy import (
    NotGiven,
    Proxy,
    _CProxy,
    as_proxy,
    drop_proxy,
    get_proxy,
    name2obj,
    obj2name,
)


class NoProxyError(ValueError):
    "Error for nonexistent proxy values"

    # pylint:disable=unnecessary-pass


class DProxy(_DProxy):
    """
    A proxy object with data. This is implemented as a type that's proxied,
    thus the object can be reconstituted by the receiver (if it knows the
    proxy class) or at least rebuilt when the original sender gets the
    proxy structure back (if it doesn't). The object's state is included.
    """

    def __init__(self, name, a, k):
        a = list(a) if a else []
        super().__init__(name, a, k)

    def append(self, val):
        "Helper for deserializer"
        self.a.append(val)

    def __setitem__(self, key, val):
        "Helper for deserializer"
        self.k[key] = val

    def __reduce__(self):
        return (type(self), self.a, self.k)


as_proxy("_", NotGiven)
as_proxy("_p", Proxy)

as_proxy("_fp", FSPath)
as_proxy("_fpa", AioPath)


def _next(it, dfl=None):
    try:
        return next(it)
    except StopIteration:
        return dfl


def wrap_obj(obj, name=None):
    "Serialize an object"
    if name is None:
        name = obj2name(type(obj))
    try:
        p = obj.__reduce__()
        if not isinstance(p, (list, tuple)):
            res = (name, (), p)
        elif hasattr(p[0], "__name__"):  # grah
            if p[0].__name__ == "_reconstructor":
                _, _o, ak = p
                if len(ak) == 1:
                    k = ak
                    a = []
                else:
                    a, k = ak
                res = [
                    name,
                ] + a
                if k or (a and isinstance(a[-1], dict)):
                    res.append(k)
            elif p[0].__name__ == "__newobj__":
                raise NotImplementedError(p)
                res = (p[1][0], p[1][1:]) + tuple(p[2:])
            else:
                res = (name,) + p[1]
                if (len(p) == 3 and p[2]) or isinstance(p[-1], dict):
                    res += (p[2],)
                elif len(p) > 3:
                    raise NotImplementedError(p)

        elif p[0] is not type(obj):
            raise ValueError(f"Reducer for {obj!r}")
        else:
            raise NotImplementedError(p)
            res = (name,) + p[1]
        return res

    except (AttributeError, ValueError):
        p = obj.__getstate__()
        if isinstance(p, dict):
            p = (p,)
        return (name,) + p


def unwrap_obj(s):
    "Deserialize an object"
    pk, *a = s
    if not isinstance(pk, type):
        # otherwise it was tagged and de-proxied already
        if isinstance(pk, Proxy):
            pk = pk.name
        try:
            pk = _CProxy[pk]
        except KeyError:
            kw = a.pop() if a and isinstance(a[-1], dict) else {}
            return DProxy(pk, a, kw)
    if a and isinstance(a[-1], dict):
        kw = a.pop()
    else:
        kw = {}

    if isfunction(pk):
        return pk(*a, **kw)

    if (pkr := getattr(pk, "_moat__restore", None)) is not None:
        pk = pkr(a, kw)
    else:
        try:
            pk = pk(*a, **kw)
        except (TypeError, ValueError):
            if not issubclass(pk, Exception):
                raise
            pk = pk(*a)
            for k, v in kw.items():
                setattr(pk, k, v)
    return pk
