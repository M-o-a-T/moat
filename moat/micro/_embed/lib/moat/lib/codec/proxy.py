"""
A hacked-up copy of some parts of `moat.util`.
"""

from __future__ import annotations

from ._proxy import (  # noqa:F401
    DProxy,
    NoProxyError,
    Proxy,
    _CProxy,
    _RProxy,
    as_proxy,
    drop_proxy,
    get_proxy,
    name2obj,
    obj2name,
)

__all__ = [
    "DProxy",
    "NoProxyError",
    "Proxy",
    "as_proxy",
    "drop_proxy",
    "get_proxy",
    "name2obj",
    "obj2name",
    "unwrap_obj",
    "wrap_obj",
]


def wrap_obj(obj, name=None):
    "Serialize an object"
    if name is None:
        name = obj2name(type(obj))
    if isinstance(obj, Exception):
        return name, obj.args
    try:
        p = obj.__dict__
    except AttributeError:
        p = {}
        for n in dir(obj):
            if n.startswith("_"):
                continue
            p[n] = getattr(obj, n)
    return (name, (), p)


def unwrap_obj(s):
    "Deserialize an object"
    s, *d = list(s)
    st = d.pop() if d and isinstance(d[-1], dict) else {}
    try:
        p = name2obj(s)
        if hasattr(p, "__setstate__"):
            o = p(*d)
            p.__setstate__(st)
        else:
            o = p(*d, **st)
    except KeyError:
        o = DProxy(s, d, st)
    except TypeError:
        o = p(*d)
        try:
            o.__dict__.update(st)
        except AttributeError:
            for k, v in st.items():
                setattr(o, k, v)
    return o
