"""
This module contains proxy helpers.
"""

from __future__ import annotations

from .impl import NotGiven

__all__ = [
    "Proxy",
    "DProxy",
    "NoProxyError",
    "as_proxy",
    "name2obj",
    "obj2name",
    "get_proxy",
    "drop_proxy",
]


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
    A proxy object with data, i.e. an object of a proxied class which
    the receiver doesn't know about
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


_pkey = 1
_CProxy: dict[str, object] = {}
_RProxy: dict[int, str] = {}


def get_proxy(obj):
    """
    Return a proxy for @obj.

    If no proxy for it exists, a new one is created.
    """
    try:
        return _RProxy[id(obj)]
    except KeyError:
        global _pkey  # noqa:PLW0603 pylint:disable=global-statement
        k = "p_" + str(_pkey)
        _pkey += 1
        _CProxy[k] = obj
        _RProxy[id(obj)] = k
        return k


def drop_proxy(p):
    """
    After sending a proxy we keep it in memory in case the remote returns
    it, or an expression with it.

    If that won't happen, the remote needs to tell us to clean it up.
    """
    if not isinstance(p, str):
        p = _RProxy[id(p)]
    if p == "" or p[0] == "_":
        raise ValueError("Can't delete a system proxy")
    r = _CProxy.pop(p)
    del _RProxy[id(r)]


def name2obj(name, obj=NotGiven, replace=False):
    """
    Translates Proxy name to referred object

    Raises `KeyError` if not found.
    """
    if obj is NotGiven and not replace:
        return _CProxy[name]
    if replace:
        _CProxy[name] = obj
    else:
        oobj = _CProxy.get(name)
        if oobj is not None and oobj is not obj:
            raise KeyError(name)  # exists
    return None


def obj2name(obj, name=NotGiven, replace=False):
    """
    Translates Proxy object to proxied name

    If a name is given, set it.

    Raises `KeyError` if not found and no name given, or if the oid
    already has a different name.
    """
    if name is NotGiven and not replace:
        return _RProxy[id(obj)]
    oid = id(obj)
    if replace:
        _RProxy[oid] = name
    else:
        oname = _RProxy.get(oid)
        if oname is not None and oname != name:
            raise KeyError(name)  # exists
    return None


def as_proxy(name, obj=NotGiven, replace=False):
    """
    Export an object or class as a named proxy.

    @replace can be
    - False (default): error when the name exists
    - True: replace the stored name
    - None: replace the object

    @codec is used on MicroPython for built-in classes that need
    special handling. It is ignored on CPython.
    """

    def _proxy(obj):
        if replace is None and name in _CProxy:
            return _CProxy[name]
        _RProxy[id(obj)] = name
        _CProxy[name] = obj
        return obj

    if _CProxy and obj is NotGiven:
        # this allows us to register the NotGiven object
        return _proxy
    else:
        _proxy(obj)
        return obj


as_proxy("_", NotGiven, replace=True)
as_proxy("_p", Proxy)
