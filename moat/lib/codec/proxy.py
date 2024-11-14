"""
This module contains proxy helpers.
"""

from __future__ import annotations

from inspect import isfunction

__all__ = [
    "Proxy",
    "DProxy",
    "NoProxyError",
    "as_proxy",
    "name2obj",
    "obj2name",
    "get_proxy",
    "drop_proxy",
    "NotGiven",
]


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable

NotGiven = ...


class NoProxyError(ValueError):
    "Error for nonexistent proxy values"

    # pylint:disable=unnecessary-pass


class Proxy:
    """
    A proxy object, i.e. a placeholder for something that cannot pass
    through a codec. No object data are included.
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
    A proxy object with data. This is implemented as a type that's proxied,
    thus the object can be reconstituted by the receiver (if it knows the
    proxy class) or at least rebuilt when the original sender gets the
    proxy structure back (if it doesn't). The object's state is included.
    """

    def __init__(self, name, i=(), s=None, a=(), k=None):
        super().__init__(name)
        self.i = i
        self.s = s
        self.a = list(a) if a else []
        self.k = k or {}

    def __getitem__(self, i):
        if i in self.k:
            return self.k[i]
        else:
            return self.a[i]

    def append(self, val):
        "Helper for deserializer"
        self.a.append(val)

    def __setitem__(self, key, val):
        "Helper for deserializer"
        self.k[key] = val

    def __repr__(self):
        return (
            f"{self.__class__.__name__}({self.name!r},"
            + ",".join(repr(x) for x in (self.a, self.k))
            + ")"
        )

    def __reduce__(self):
        return (type(self), self.i, self.s, self.a, self.k)


_pkey = 1
_CProxy: dict[str, tuple[object, callable | None]] = {}
_RProxy: dict[int, str] = {}


def get_proxy(obj, factory: Callable | None = None):
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
        _CProxy[k] = (obj, factory)
        _RProxy[id(obj)] = k
        if factory:
            _RProxy[id(factory)] = k
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
    r, f = _CProxy.pop(p)
    del _RProxy[id(r)]
    if f is not None:
        del _RProxy[id(f)]


def name2obj(
    name, obj: object | type = NotGiven, replace: bool = False, factory: Callable | None = None,
):
    """
    Translates Proxy name to referred object

    Raises `KeyError` if not found.
    """
    if obj is NotGiven and not replace:
        return _CProxy[name][0]
    if replace:
        _CProxy[name] = (obj, factory)
    else:
        oobj, _f = _CProxy.get(name)
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


def as_proxy(name, obj=NotGiven, replace=False, factory=None):
    """
    Export an object or class as a named proxy.

    @replace can be
    - False (default): error when the name exists
    - True: replace the stored name
    - None: replace the object
    """

    def _proxy(obj):
        if replace is None and name in _CProxy:
            return _CProxy[name][0]
        _RProxy[id(obj)] = name
        _CProxy[name] = (obj, factory)
        return obj

    if _CProxy and obj is NotGiven:
        # this allows us to register the NotGiven object
        return _proxy
    else:
        _proxy(obj)
        return obj


def _NG(*_a):
    return Ellipsis


as_proxy("_", NotGiven, replace=True, factory=_NG)
as_proxy("_p", Proxy)


def _next(it, dfl=None):
    try:
        return next(it)
    except StopIteration:
        return dfl


def wrap_obj(data, name=None):
    "Serialize an object"
    if name is None:
        name = obj2name(type(data))
    try:
        p = data.__reduce__()
        if not isinstance(p, (list, tuple)):
            p = (name, (), p)
        else:
            if p[0] is not type(data):
                raise ValueError(f"Reducer for {data!r}")
            p = (name,) + p[1:]
        return p

    except (AttributeError, ValueError):
        p = data.__getstate__()
        if not isinstance(p, (list, tuple)):
            p = (
                (),
                p,
            )
        return (name,) + p


def unwrap_obj(s):
    "Deserialize an object"
    s = iter(list(s))
    pk = next(s)
    if not isinstance(pk, type):
        # otherwise it was tagged and de-proxied already
        if isinstance(pk, Proxy):
            pk = pk.name
        try:
            pk, f = _CProxy[pk]
        except KeyError:
            return DProxy(pk, *s)
        pk = f or pk
    if isfunction(pk):
        return pk(*s)

    a = _next(s, ())
    if isinstance(a, dict):
        # old version
        kw = a
        a = ()
        st = NotGiven
    else:
        kw = {}
        st = _next(s, None) or {}

    try:
        pk = pk(*a, **kw)
    except TypeError:
        pk = pk(*a, **st)
    else:
        try:
            pk.__setstate__(st)
        except AttributeError:
            if st:
                for k, v in st.items():
                    pk[k] = v
    for v in _next(s, ()):
        pk.append(v)
    for k, v in _next(s, {}).items():
        pk[k] = v

    return pk
