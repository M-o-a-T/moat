"""Tests for the moat.link.ow model and helpers."""

from __future__ import annotations

import pytest

from moat.lib.path import P, Path
from moat.link.meta import MsgMeta
from moat.link.ow.model import (
    AttrCfg,
    OwAttr,
    OwDevice,
    OwFamily,
    OwRoot,
    OwServer,
    OwServers,
    fmt_device,
    fmt_family,
    parse_at,
)


def _meta(t=1):
    return MsgMeta(origin="t", t=t)


def _p(*a) -> Path:
    "Build a path. (P() would parse numbers as strings.)"
    res = []
    for x in a:
        res.extend(P(x) if isinstance(x, str) else (x,))
    return Path.build(res)


def test_fmt():
    "Family and device codes are shown as 2 and 12 hex digits."
    assert fmt_family(0x10) == "10"
    assert fmt_family(5) == "05"
    assert fmt_device(0x10, 0x0BAC6B010800) == "10.0bac6b010800"
    assert fmt_device(5, 0x678) == "05.000000000678"


def test_parse_at():
    "FAMILY[.CODE[.ATTR…]] parses into ints and an attribute path."
    assert parse_at("10") == (0x10, None, Path())
    assert parse_at("10.0bac6b010800") == (0x10, 0x0BAC6B010800, Path())
    assert parse_at("10.0BAC6B010800.temperature") == (0x10, 0x0BAC6B010800, P("temperature"))
    assert parse_at("05.345678.foo.plugh:1") == (5, 0x345678, P("foo.plugh:1"))


@pytest.mark.parametrize("bad", ["", "x", "123", "10.", "10.xyz", "10.1234567890123"])
def test_parse_at_bad(bad):
    "Malformed family or device codes are rejected."
    with pytest.raises(ValueError, match="1-Wire"):
        parse_at(bad)


def test_tree_types():
    "The tree creates the correct node types at each level."
    root = OwRoot()
    assert isinstance(root.add_child("server"), OwServers)
    assert isinstance(root.get(P("server.pi")), OwServer)
    fam = root.add_child(0x10)
    assert isinstance(fam, OwFamily)
    dev = fam.add_child(0x345678)
    assert isinstance(dev, OwDevice)
    attr = dev.add_child("foo")
    assert isinstance(attr, OwAttr)
    assert isinstance(attr.add_child("bar"), OwAttr)


def test_server_cfg():
    "A server's settings are below its 'server' key."
    root = OwRoot()
    root.set(P("server.pi"), {"server": {"host": "pi", "port": 1234}}, _meta())
    assert root.get(P("server.pi")).cfg == {"host": "pi", "port": 1234}


def test_attr_cfg():
    "AttrCfg converts paths and reports the direction."
    c = AttrCfg.build({"dest": ("a", "b"), "interval": 5, "dest_attr": ("baz", 2)})
    assert c.dest == P("a.b")
    assert c.dest_attr == P("baz:2")
    assert c.interval == 5
    assert c.is_read
    assert not c.is_write
    assert c.is_complete()

    c = AttrCfg.build({"src": ("cmd",), "idem": False})
    assert c.src == P("cmd")
    assert c.idem is False
    assert c.is_write
    assert not c.is_read

    c = AttrCfg.build({"interval": 5})
    assert not c.is_complete()
    assert AttrCfg.build().idem is True


def test_inheritance():
    "An attribute's settings are merged over its device's and family's."
    root = OwRoot()
    root.set(_p(16), {"interval": 30, "idem": False}, _meta())
    root.set(_p(16, 0x345678), {"interval": 10}, _meta())
    root.set(_p(16, 0x345678, "temperature"), {"dest": P("a")}, _meta())
    root.set(_p(16, 0x345678, "humidity"), {"dest": P("b"), "interval": 5}, _meta())
    root.set(_p(16, 0x999, "temperature"), {"dest": P("c")}, _meta())

    c = root.attr_cfg(16, 0x345678, P("temperature"))
    assert c == AttrCfg(dest=P("a"), interval=10, idem=False)
    assert root.attr_cfg(16, 0x345678, P("humidity")).interval == 5
    assert root.attr_cfg(16, 0x999, P("temperature")).interval == 30
    assert root.attr_cfg(16, 0x345678, P("nope")) is None
    assert root.attr_cfg(17, 0x345678, P("temperature")) is None


def test_attrs():
    "The mappings below a family or device are found, including nested ones."
    root = OwRoot()
    root.set(_p(16, 1, "temperature"), {"dest": P("a")}, _meta())
    root.set(_p(16, 1, "foo.bar"), {"dest": P("b")}, _meta())
    root.set(_p(16, 2, "temperature"), {"dest": P("c")}, _meta())
    root.set(_p(17, 1, "temperature"), {"dest": P("d")}, _meta())

    assert set(root.attrs(16)) == {
        (16, 1, P("temperature")),
        (16, 1, P("foo.bar")),
        (16, 2, P("temperature")),
    }
    assert set(root.attrs(16, 2)) == {(16, 2, P("temperature"))}
    assert set(root.attrs(18)) == set()
