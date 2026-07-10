"""Tests for the moat.link.ow model and helpers."""

from __future__ import annotations

import pytest

from moat.lib.path import P
from moat.link.meta import MsgMeta
from moat.link.ow.model import (
    OwAttr,
    OwDevice,
    OwFamily,
    OwRoot,
    OwServer,
    device_subpath,
    parse_device,
)


def test_parse_device_basic():
    """``FF.CODE.CHK`` parses into the ``(family, code)`` integer pair."""
    assert parse_device("10.345678.90") == (0x10, 0x345678)
    assert parse_device("28.abcdef.01") == (0x28, 0xABCDEF)


def test_parse_device_rejects_bad():
    """Non-3-part ids are rejected."""
    with pytest.raises(ValueError, match="3-part"):
        parse_device("10.345678")
    with pytest.raises(ValueError, match="3-part"):
        parse_device("10.345678.90.ab")


def test_device_subpath():
    """`device_subpath` returns the ``(family, code)`` int path."""
    p = device_subpath("10.345678.90")
    assert tuple(p) == (0x10, 0x345678)


def test_tree_typed_add_child():
    """The tree creates the correct subclasses at each level."""
    root = OwRoot()
    srv = root.add_child("s1")
    assert isinstance(srv, OwServer)
    fam = srv.add_child(0x10)
    assert isinstance(fam, OwFamily)
    dev = fam.add_child(0x345678)
    assert isinstance(dev, OwDevice)
    attr = dev.add_child("temperature")
    assert isinstance(attr, OwAttr)
    # nested attribute segments stay OwAttr
    nested = attr.add_child("bar")
    assert isinstance(nested, OwAttr)


def test_attr_properties_read():
    """``OwAttr`` exposes its read-direction config fields."""
    a = OwAttr()
    a.set_(
        (),
        {
            "dest": ("data", "temp", "room"),
            "interval": 5,
            "dest_attr": ("baz", 2),
        },
        MsgMeta(origin="test", t=1),
    )
    assert a.dest == P("data.temp.room")
    assert a.interval == 5
    assert a.dest_attr == P("baz:2")
    assert a.src is None
    assert a.is_read
    assert not a.is_write
    assert a.is_complete()


def test_attr_properties_write():
    """``OwAttr`` exposes its write-direction config fields."""
    a = OwAttr()
    a.set_(
        (),
        {
            "src": ("cmd", "low"),
            "src_attr": ("bar", 1),
            "idem": False,
        },
        MsgMeta(origin="test", t=1),
    )
    assert a.src == P("cmd.low")
    assert a.src_attr == P("bar:1")
    assert a.idem is False
    assert a.is_write
    assert not a.is_read
    assert a.is_complete()


def test_attr_incomplete():
    """``is_complete`` requires either dest or src."""
    a = OwAttr()
    assert not a.is_complete()

    a.set_((), {"interval": 5}, MsgMeta(origin="t", t=1))
    assert not a.is_complete()  # neither dest nor src

    a.set_((), {"dest": ("a",)}, MsgMeta(origin="t", t=2))
    assert a.is_complete()


def test_attr_defaults():
    """Empty / unset entries report sane defaults."""
    a = OwAttr()
    assert a.dest is None
    assert a.src is None
    assert a.interval is None
    assert a.dest_attr is None
    assert a.src_attr is None
    assert a.idem is True


def test_typed_watcher_round_trip():
    """An OwRoot built up via ``set`` keeps the type chain consistent."""
    root = OwRoot()
    root.set(
        P("s1.16.345678.temperature"),
        {"dest": ("a", "b"), "interval": 4},
        MsgMeta(origin="t", t=1),
    )
    leaf = root.get(P("s1.16.345678.temperature"))
    assert isinstance(leaf, OwAttr)
    assert leaf.is_complete()
    assert leaf.dest == P("a.b")
    assert leaf.interval == 4
