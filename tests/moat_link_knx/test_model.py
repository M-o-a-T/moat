"""Tests for the moat.link.knx model and helpers."""

from __future__ import annotations

import pytest

from moat.lib.path import P
from moat.link.knx.model import (
    KnxEntry,
    KnxMain,
    KnxMiddle,
    KnxRoot,
    KnxServer,
    group_subpath,
    parse_group,
)
from moat.link.meta import MsgMeta


def test_parse_group_basic():
    """``a/b/c`` parses into the matching 3-tuple of ints."""
    assert parse_group("1/2/3") == (1, 2, 3)
    assert parse_group("0/0/0") == (0, 0, 0)
    assert parse_group("31/7/255") == (31, 7, 255)


def test_parse_group_rejects_2level():
    """A 2-part group address is not valid here."""
    with pytest.raises(ValueError, match="3-part"):
        parse_group("1/2")


def test_group_subpath():
    """`group_subpath` returns an int-typed :class:`Path`."""
    p = group_subpath("1/2/3")
    assert tuple(p) == (1, 2, 3)


def test_tree_typed_add_child():
    """The tree creates the correct subclasses at each level."""
    root = KnxRoot()
    srv = root.add_child("g1")
    assert isinstance(srv, KnxServer)
    main = srv.add_child(1)
    assert isinstance(main, KnxMain)
    middle = main.add_child(2)
    assert isinstance(middle, KnxMiddle)
    leaf = middle.add_child(3)
    assert isinstance(leaf, KnxEntry)


def test_entry_properties():
    """``KnxEntry`` exposes its config fields."""
    e = KnxEntry()
    e.set_(
        (),
        {
            "type": "in",
            "mode": "Bool",
            "dest": ("data", "foo", "bar"),
        },
        MsgMeta(origin="test", t=1),
    )
    assert e.type_ == "in"
    assert e.mode == "Bool"
    assert e.dest == P("data.foo.bar")
    assert e.src is None
    assert e.is_complete()


def test_entry_incomplete():
    """``is_complete`` requires the relevant path field."""
    e = KnxEntry()
    assert not e.is_complete()

    e.set_((), {"type": "out", "mode": "Bool"}, MsgMeta(origin="t", t=1))
    assert not e.is_complete()  # missing src

    e.set_((), {"type": "out", "mode": "Bool", "src": ("a",)}, MsgMeta(origin="t", t=2))
    assert e.is_complete()


def test_entry_state_property():
    """``KnxEntry.state`` exposes the optional state path."""
    e = KnxEntry()
    e.set_(
        (),
        {
            "type": "out",
            "mode": "Bool",
            "src": ("cmd", "x"),
            "state": ("state", "x"),
        },
        MsgMeta(origin="t", t=1),
    )
    assert e.state == P("state.x")

    e2 = KnxEntry()
    e2.set_(
        (),
        {"type": "out", "mode": "Bool", "src": ("cmd",)},
        MsgMeta(origin="t", t=1),
    )
    assert e2.state is None


def test_typed_watcher_round_trip():
    """A KnxRoot built up via ``set`` keeps the type chain consistent."""
    root = KnxRoot()
    root.set(
        P("g1.1.2.3"),
        {"type": "in", "mode": "Bool", "dest": ("a", "b")},
        MsgMeta(origin="t", t=1),
    )
    leaf = root.get(P("g1.1.2.3"))
    assert isinstance(leaf, KnxEntry)
    assert leaf.is_complete()
