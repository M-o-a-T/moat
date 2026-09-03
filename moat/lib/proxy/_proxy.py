"""
A hacked-up copy of some parts of `moat.util`.

Proxies are named references to objects that cannot be serialized directly.
Named proxies (registered via ``as_proxy``) are held strongly and persist
until explicitly dropped. Auto-generated proxies (created by ``get_proxy``
when encoding an unknown object) are held weakly: they are released
automatically when the referenced object is garbage-collected.

To avoid dropping an auto proxy *prematurely* (e.g. between encoding an
object and decoding the resulting reference while no caller holds it), the
most recently auto-proxied objects are also kept alive in a tiny LRU
(``_pins``). Eviction from the LRU only releases that strong pin; the
weakref entry survives as long as the object itself is reachable, so a
still-live object remains referable after ageing out of the LRU.
"""

from __future__ import annotations

from weakref import WeakValueDictionary, finalize

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

# Strong references for named proxies registered via ``as_proxy``.
# Also holds objects that cannot be weak-referenced (e.g. ``Ellipsis``).
# These persist until ``drop_proxy`` is called.
_SProxy: dict[str, Any] = {}

# Name → object. Auto-generated proxies are held weakly;
# named proxies are kept alive by ``_SProxy``.
# Objects that don't support weakrefs are stored in ``_SProxy`` instead.
_CProxy: WeakValueDictionary[str, Any] = WeakValueDictionary()

# id(obj) → name. Entries for auto-generated proxies are removed
# automatically when the object is garbage-collected (via the
# finalizer installed in ``get_proxy``). Named-proxy entries
# persist because ``_SProxy`` keeps the object alive.
_RProxy: dict[int, str] = {}

#: Number of recently auto-proxied objects kept alive as a safeguard
#: against premature garbage-collection between encode and decode.
_LRU_SIZE = 5

#: Most recently auto-proxied objects (strong refs), oldest first. Eviction
#: only releases this strong pin; ``_CProxy``/``_RProxy`` are left intact so
#: a still-live object remains referable after ageing out of the LRU.
_pins: list[Any] = []


def _try_weakref(obj: Any) -> bool:
    """Return True if *obj* supports weak references."""
    try:
        finalize(obj, lambda: None)  # type: ignore[arg-type]
    except TypeError:
        return False
    return True


def _store_proxy(name: str, obj: Any) -> None:
    """
    Store a proxy entry.

    Objects that support weak references go into ``_CProxy`` (weak).
    Objects that don't (e.g. ``Ellipsis``, builtins) go into ``_SProxy``
    (strong) as a fallback.
    """
    if _try_weakref(obj):
        _CProxy[name] = obj
    else:
        _SProxy[name] = obj


def _lookup_proxy(name: str) -> Any:
    """Look up a proxy by name, checking both weak and strong stores."""
    try:
        return _CProxy[name]
    except KeyError:
        return _SProxy[name]


def _pop_proxy(name: str) -> Any:
    """Remove and return a proxy from whichever store holds it."""
    try:
        return _CProxy.pop(name)
    except KeyError:
        return _SProxy.pop(name)


def _register_named(name: str, obj: Any) -> None:
    """Register a named proxy with a strong reference."""
    _SProxy[name] = obj
    if _try_weakref(obj):
        _CProxy[name] = obj
    _RProxy[id(obj)] = name


def _track_finalizer(obj: Any, oid: int) -> None:
    """
    Install a finalizer that removes the ``_RProxy`` entry for *obj*
    when it is garbage-collected.

    Objects that do not support weak references are skipped — the entry
    in ``_RProxy`` will persist but is harmless.
    """
    try:
        finalize(obj, _RProxy.pop, oid, None)
    except TypeError:
        pass  # Object doesn't support weakrefs; nothing to clean up.


def _evict() -> None:
    """Release the oldest strong pins down to ``_LRU_SIZE``.

    Only the pin is dropped; ``_CProxy`` and ``_RProxy`` are left untouched,
    so a still-reachable object keeps resolving after ageing out of the LRU.
    """
    while len(_pins) > _LRU_SIZE:
        _pins.pop(0)


def _pin(obj: Any) -> None:
    """Add a strong pin for a newly auto-proxied object."""
    _pins.append(obj)
    _evict()


def _promote(obj: Any) -> None:
    """Move *obj* to the most-recently-used end of the auto LRU.

    Comparison is by identity so that objects with a custom ``__eq__`` are
    not confused with equal-but-distinct instances. An object that aged out
    of the LRU but is still alive is re-pinned.
    """
    for i, o in enumerate(_pins):
        if o is obj:
            del _pins[i]
            _pins.append(obj)
            return
    _pins.append(obj)
    _evict()


def _unpin(obj: Any) -> None:
    """Remove *obj*'s strong pin if present (identity comparison)."""
    for i, o in enumerate(_pins):
        if o is obj:
            del _pins[i]
            return


@overload
def name2obj(name: str) -> Any: ...


@overload
def name2obj(name: str, obj: Any) -> None: ...


def name2obj(name: str, obj: Any = NotGiven) -> Any | None:
    """
    Given a proxy name, return the referred object.

    If @obj is given, associate.
    """
    if obj is NotGiven:
        return _lookup_proxy(name)
    _register_named(name, obj)
    return None


def obj2name(obj: object) -> str:
    """
    Given a proxied object, return the name referring to it.
    """
    return _RProxy[id(obj)]


def get_proxy(obj: object) -> str:
    """
    Given a proxied object, return the name referring to it.

    If unknown, create a new temporary name. Auto-generated proxies are
    held weakly: when the object is garbage-collected the proxy entry
    is removed automatically.

    The most recently auto-proxied objects are also pinned in a small LRU
    (``_pins``) so they survive brief windows in which no caller holds
    a reference (e.g. between encoding and decoding). Re-using ``get_proxy``
    on an already-known object refreshes its position in that LRU.
    """
    name = _RProxy.get(id(obj))
    if name is not None:
        _promote(obj)
        return name
    global _pkey
    name = "p_" + str(_pkey)
    _pkey += 1
    _store_proxy(name, obj)
    _RProxy[id(obj)] = name
    _track_finalizer(obj, id(obj))
    _pin(obj)
    return name


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

    Named proxies are held with strong references and persist until
    ``drop_proxy`` is called.

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
        if not replace and name in _SProxy and _SProxy[name] is not obj:
            raise ValueError("Proxy: " + repr(name) + " already exists")
        _register_named(name, obj)
        return obj

    if obj is NotImplemented:
        return _proxy
    else:
        _proxy(obj)
        return obj


def drop_proxy(p: str | object) -> None:
    """
    Drop a named proxy.

    After sending a proxy we keep it in memory in case the remote returns
    it, or an expression with it.

    If that won't happen, the remote needs to tell us to clean it up.
    """
    if not isinstance(p, str):
        p = _RProxy[id(p)]
    if p == "" or p[0] == "_":
        raise ValueError("Can't delete a system proxy")
    r = _pop_proxy(p)
    _SProxy.pop(p, None)
    _unpin(r)
    _RProxy.pop(id(r), None)


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
