"""Tests for the moat.link.wago model and helpers."""

from __future__ import annotations

from moat.lib.path import P
from moat.link.meta import MsgMeta
from moat.link.wago.model import WagoCard, WagoPort, WagoRoot, WagoServer, WagoType


def test_tree_typed_add_child():
    """The tree creates the correct subclasses at each level."""
    root = WagoRoot()
    srv = root.add_child("s1")
    assert isinstance(srv, WagoServer)
    typ = srv.add_child("input")
    assert isinstance(typ, WagoType)
    card = typ.add_child(1)
    assert isinstance(card, WagoCard)
    leaf = card.add_child(3)
    assert isinstance(leaf, WagoPort)


def test_port_properties():
    """``WagoPort`` exposes its config fields."""
    p = WagoPort()
    p.set_(
        (),
        {
            "mode": "read",
            "dest": ("data", "foo", "bar"),
            "rest": True,
        },
        MsgMeta(origin="test", t=1),
    )
    assert p.mode == "read"
    assert p.dest == P("data.foo.bar")
    assert p.rest is True
    assert p.src is None
    assert p.is_complete()


def test_port_incomplete():
    """``is_complete`` requires the relevant path field."""
    p = WagoPort()
    assert not p.is_complete()

    p.set_((), {"mode": "write"}, MsgMeta(origin="t", t=1))
    assert not p.is_complete()  # missing src

    p.set_(
        (),
        {"mode": "write", "src": ("a",)},
        MsgMeta(origin="t", t=2),
    )
    assert p.is_complete()


def test_port_state_property():
    """``WagoPort.state`` exposes the optional state path."""
    p = WagoPort()
    p.set_(
        (),
        {
            "mode": "write",
            "src": ("cmd", "x"),
            "state": ("state", "x"),
        },
        MsgMeta(origin="t", t=1),
    )
    assert p.state == P("state.x")

    p2 = WagoPort()
    p2.set_(
        (),
        {"mode": "write", "src": ("cmd",)},
        MsgMeta(origin="t", t=1),
    )
    assert p2.state is None


def test_typed_watcher_round_trip():
    """A WagoRoot built up via ``set`` keeps the type chain consistent."""
    root = WagoRoot()
    root.set(
        P("s1.input.1.3"),
        {"mode": "read", "dest": ("a", "b")},
        MsgMeta(origin="t", t=1),
    )
    leaf = root.get(P("s1.input.1.3"))
    assert isinstance(leaf, WagoPort)
    assert leaf.is_complete()
