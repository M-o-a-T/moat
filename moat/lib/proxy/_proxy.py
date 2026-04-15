"""
A hacked-up copy of some parts of `moat.util`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, overload

if TYPE_CHECKING:
    from types import NotImplementedType

    from collections.abc import Callable
    from typing import Any, TypeVar

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

NotGiven: object = ...  # from moat.util import NotGiven


_pkey: int = 1
_CProxy: dict[str, Any] = {}  # name > object
_RProxy: dict[int, str] = {}  # object > name


@overload
def name2obj(name: str) -> Any: ...


@overload
def name2obj(name: str, obj: Any) -> None: ...


def name2obj(name: str, obj: Any = NotGiven) -> Any | None:
    """
    Given a proxy name, return the referred object.

    If @obj is given, associate.
    """
    if obj is NotGiven and _CProxy:
        return _CProxy[name]
    _CProxy[name] = obj
    _RProxy[id(obj)] = name
    return None


def obj2name(obj: object) -> str:
    """
    Given a proxied object, return the name referring to it.
    """
    return _RProxy[id(obj)]


def get_proxy(obj: object) -> str:
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
    def as_proxy(name: str, obj: T, replace: bool = False) -> T: ...


def as_proxy(
    name: str, obj: Any | NotImplementedType = NotImplemented, replace: bool = False
) -> Any | Callable[[T], T]:
    """
    Export an object as a named proxy.

    Usage::

        @as_proxy("foo")
        class Foo:
            pass
    """
    # This uses NotImplemented instead of None or Ellipsis/NotGiven because
    # those two are be legitimately proxied.

    def _proxy(obj: T) -> T:
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


def drop_proxy(p: str | object) -> None:
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

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name!r})"

    def ref(self) -> Any:
        """Dereferences the proxy"""
        return name2obj(self.name)


class DProxy(Proxy):
    """
    A proxy object with data. This is implemented as a type that's proxied,
    thus the object can be reconstituted by the receiver (if it knows the
    proxy class) or at least rebuilt when the original sender gets the
    proxy structure back (if it doesn't). The object's state is included.
    """

    def __init__(self, name: str, a: list[Any], k: dict[str, Any]) -> None:
        super().__init__(name)
        self.a = a
        self.k = k

    def __getitem__(self, i: object) -> Any:
        if i in self.k:
            return self.k[cast(str, i)]
        else:
            try:
                return self.a[cast(int, i)]
            except TypeError:
                from moat.lib.micro import log  # noqa: PLC0415

                log("*ERR %r", self.k)
                raise KeyError(i) from None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DProxy):
            return False

        # Split into several lines so we can selectively set breakpoints
        # when debugging
        if self.name != other.name:
            return False
        if self.a != other.a or self.k != other.k:
            return False
        return True

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}({self.name!r},"
            + ",".join(repr(x) for x in (self.a, self.k))
            + ")"
        )

    def ref(self) -> Any:
        """Dereferences the proxy"""
        return name2obj(self.name)
