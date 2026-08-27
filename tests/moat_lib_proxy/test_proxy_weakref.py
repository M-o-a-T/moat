"""
Tests for auto-generated proxy weakref release.

These tests verify that auto-generated proxies (created by ``get_proxy``)
are automatically released when the referenced object is garbage-collected,
while named proxies (registered via ``as_proxy``) persist until explicitly
dropped.
"""

from __future__ import annotations

import gc
import pytest

from moat.util import NotGiven
from moat.lib.codec.moat_cbor import Codec as StdCBOR
from moat.lib.proxy import (
    as_proxy,
    drop_proxy,
    get_proxy,
    name2obj,
    obj2name,
)
from moat.lib.proxy._proxy import _LRU_SIZE, _CProxy, _SProxy


class Widget:
    """A test object for proxying."""

    def __init__(self, x):
        self.x = x

    def __eq__(self, other):
        return isinstance(other, Widget) and self.x == other.x

    def __repr__(self):
        return f"<Widget:{self.x}>"


# needs "replace" because testing re-imports
@as_proxy("widget_test")
class RegisteredWidget(Widget):
    "A registered proxy class."


def test_auto_proxy_release():
    """Auto-generated proxies are released once aged out of the LRU and GC'd."""
    w = Widget(42)
    name = get_proxy(w)
    assert name.startswith("p_")
    assert name2obj(name) is w
    assert obj2name(w) == name

    # Age `w` out of the LRU so it's no longer pinned.
    for i in range(_LRU_SIZE):
        get_proxy(Widget(100 + i))

    # Still alive despite having aged out of the LRU: the weakref cache,
    # not the pin, keeps it referable.
    assert name2obj(name) is w

    # Drop our reference and force GC
    del w
    gc.collect()

    # The proxy should be gone
    with pytest.raises(KeyError):
        name2obj(name)


def test_auto_proxy_survives_while_referenced():
    """Auto-generated proxies survive as long as the object is reachable."""
    w = Widget(99)
    name = get_proxy(w)
    gc.collect()
    assert name2obj(name) is w
    assert obj2name(w) == name


def test_named_proxy_persists():
    """Named proxies survive GC because they're held strongly."""
    w = Widget(77)
    as_proxy("named_w", w)
    assert name2obj("named_w") is w

    del w
    gc.collect()

    # Should still be there
    assert name2obj("named_w").x == 77


def test_drop_named_proxy():
    """drop_proxy removes named proxies."""
    w = Widget(55)
    as_proxy("droppable", w)
    assert name2obj("droppable") is w

    drop_proxy("droppable")

    with pytest.raises(KeyError):
        name2obj("droppable")


def test_drop_auto_proxy():
    """drop_proxy removes auto-generated proxies too."""
    w = Widget(33)
    name = get_proxy(w)
    assert name2obj(name) is w

    drop_proxy(name)

    with pytest.raises(KeyError):
        name2obj(name)


def test_drop_proxy_by_object():
    """drop_proxy accepts the proxied object directly."""
    w = Widget(22)
    name = get_proxy(w)
    drop_proxy(w)

    with pytest.raises(KeyError):
        name2obj(name)


def test_system_proxy_not_droppable():
    """System proxies (starting with _) cannot be dropped."""
    with pytest.raises(ValueError, match="system proxy"):
        drop_proxy("_")
    with pytest.raises(ValueError, match="system proxy"):
        drop_proxy("_p")


def test_get_proxy_reuses():
    """get_proxy returns the same name for the same object."""
    w = Widget(11)
    name1 = get_proxy(w)
    name2 = get_proxy(w)
    assert name1 == name2


def test_get_proxy_unique():
    """get_proxy returns unique names for different objects."""
    w1 = Widget(1)
    w2 = Widget(2)
    name1 = get_proxy(w1)
    name2 = get_proxy(w2)
    assert name1 != name2


def test_non_weakreferenceable_proxy():
    """Objects that can't be weakreferenced still work via strong fallback."""
    # Ellipsis (NotGiven) is registered via as_proxy and can't be weakref'd
    # This works because as_proxy stores it in _SProxy
    assert name2obj("_") is NotGiven


def test_cbor_roundtrip_with_weakref():
    """Encoding and decoding with auto-proxies works correctly when
    the original object is kept alive.
    """
    codec = StdCBOR()

    w = Widget(123)
    data = codec.encode(w)
    decoded = codec.decode(data)
    assert decoded == w
    assert decoded is w  # same object via proxy


def test_cbor_roundtrip_named_proxy():
    """Named proxies round-trip through CBOR correctly."""
    codec = StdCBOR()

    rw = RegisteredWidget(456)
    data = codec.encode(rw)
    decoded = codec.decode(data)
    assert decoded == rw
    assert isinstance(decoded, RegisteredWidget)


def test_auto_proxy_does_not_leak():
    """Verify that auto-generated proxies don't accumulate beyond the LRU."""
    # Create and discard many objects
    for i in range(100):
        w = Widget(i)
        get_proxy(w)
        del w

    gc.collect()

    # At most the LRU's worth of auto-proxies may still be pinned
    remaining = [k for k in _CProxy if k.startswith("p_")]
    assert len(remaining) <= _LRU_SIZE, f"Too many proxies: {remaining}"


def test_named_proxies_in_separate_store():
    """Named proxies are stored in _SProxy (strong) and _CProxy (weak)."""
    w = Widget(888)
    as_proxy("test_sep", w)
    assert "test_sep" in _SProxy
    assert "test_sep" in _CProxy
    assert name2obj("test_sep") is w

    drop_proxy("test_sep")
    assert "test_sep" not in _SProxy
    assert "test_sep" not in _CProxy
