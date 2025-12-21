"""
A hacked-up copy of some parts of `moat.util`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any, TypeVar, overload

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

NotGiven = ...  # from moat.util import NotGiven


_pkey = 1
_CProxy = {}  # name > object
_RProxy = {}  # object > name


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


def obj2name(obj):
    """
    Given a proxied object, return the name referring to it.
    """
    return _RProxy[id(obj)]


def get_proxy(obj):
    """
    Given a proxied object, return the name referring to it.

    If unknown, create a new temporary name.
    """
    try:
        return _RProxy[id(obj)]
    except KeyError:
        global _pkey
        k = "p_" + str(_pkey)
        _pkey += 1
        _CProxy[k] = obj
        _RProxy[id(obj)] = k
        return k


# def _getstate(self):
#     return (type(self), (), self.__dict__)


if TYPE_CHECKING:
    T = TypeVar("T")

    @overload
    def as_proxy(name: str) -> Callable[[T], T]: ...

    @overload
    def as_proxy(name: str, obj: Any, replace: bool = False) -> None: ...


def as_proxy(name: str, obj: Any = NotImplemented, replace: bool = False):
    """
    Export an object as a named proxy.
    Usage:

        @as_proxy("foo")
        class Foo():
            def __
    """
    # This uses NotImplemented instead of None or Ellipsis/NotGiven because
    # those two are be legitimately proxied.

    def _proxy(obj):
        "Export @obj as a proxy."
        if not replace and name in _CProxy and _CProxy[name] is not obj:
            raise ValueError("Proxy: " + repr(name) + " already exists")
        _CProxy[name] = obj
        _RProxy[id(obj)] = name
        #       if isinstance(obj,type) and not hasattr(obj,"__getstate__"):
        #           obj.__getstate__ = _getstate
        return obj

    if obj is NotImplemented:
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
    if p == "" or p[0] == "_":
        raise ValueError("Can't delete a system proxy")
    r = _CProxy.pop(p)
    del _RProxy[id(r)]


class NoProxyError(ValueError):
    "Error for nonexistent proxy values"

    # pylint:disable=unnecessary-pass


class Proxy:
    """
    A proxy object, i.e. a placeholder for things that cannot pass
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

    def __init__(self, name, a, k):
        super().__init__(name)
        self.a = a
        self.k = k

    def __getitem__(self, i):
        if i in self.k:
            return self.k[i]
        else:
            try:
                return self.a[i]
            except TypeError:
                from moat.util.compat import log  # noqa: PLC0415

                log("*ERR %r", self.k)
                raise KeyError(i) from None

    def __eq__(self, other):
        if not isinstance(other, DProxy):
            return NotImplemented

        # Split into several lines so we can selectively set breakpoints
        # when debugging
        if self.name != other.name:
            return False
        if self.a != other.a or self.k != other.k:
            return False
        return True

    def __repr__(self):
        return (
            f"{self.__class__.__name__}({self.name!r},"
            + ",".join(repr(x) for x in (self.a, self.k))
            + ")"
        )

    def ref(self):
        """Dereferences the proxy"""
        return name2obj(self.name)
