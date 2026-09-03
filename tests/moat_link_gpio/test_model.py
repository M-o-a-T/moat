"""Tests for the moat.link.gpio model."""

from __future__ import annotations

from moat.lib.path import P
from moat.link.gpio.model import (
    GpioChip,
    GpioHost,
    GpioLine,
    GpioRoot,
)
from moat.link.meta import MsgMeta


def test_tree_typed_add_child():
    """The tree creates the correct subclasses at each level."""
    root = GpioRoot()
    host = root.add_child("myhost")
    assert isinstance(host, GpioHost)
    chip = host.add_child("chip0")
    assert isinstance(chip, GpioChip)
    line = chip.add_child(5)
    assert isinstance(line, GpioLine)


def test_line_properties_empty():
    """An empty GpioLine has no config."""
    line = GpioLine()
    assert line.type_ is None
    assert line.mode is None
    assert line.dest is None
    assert line.src is None
    assert line.state is None
    assert line.low is False
    assert line.skip is True
    assert line.flow is False
    assert not line.is_complete()


def test_line_properties_input():
    """An input line with dest is complete."""
    line = GpioLine()
    line.set_(
        (),
        {"type": "input", "mode": "read", "dest": ("sensors", "btn")},
        MsgMeta(origin="test", t=1),
    )
    assert line.type_ == "input"
    assert line.mode == "read"
    assert line.dest == P("sensors.btn")
    assert line.src is None
    assert line.is_complete()


def test_line_properties_output():
    """An output line with src is complete."""
    line = GpioLine()
    line.set_(
        (),
        {"type": "output", "mode": "write", "src": ("ctrl", "lamp")},
        MsgMeta(origin="test", t=1),
    )
    assert line.type_ == "output"
    assert line.mode == "write"
    assert line.src == P("ctrl.lamp")
    assert line.dest is None
    assert line.is_complete()


def test_line_incomplete_missing_dest():
    """Input without dest is not complete."""
    line = GpioLine()
    line.set_((), {"type": "input", "mode": "read"}, MsgMeta(origin="t", t=1))
    assert not line.is_complete()


def test_line_incomplete_missing_src():
    """Output without src is not complete."""
    line = GpioLine()
    line.set_((), {"type": "output", "mode": "write"}, MsgMeta(origin="t", t=1))
    assert not line.is_complete()


def test_line_state_property():
    """The state path is exposed when set."""
    line = GpioLine()
    line.set_(
        (),
        {"type": "output", "mode": "write", "src": ("cmd",), "state": ("state",)},
        MsgMeta(origin="t", t=1),
    )
    assert line.state == P("state")


def test_line_low_flag():
    """The low flag defaults to False and is read from data."""
    line = GpioLine()
    assert line.low is False
    line.set_(
        (),
        {"type": "input", "mode": "read", "low": True, "dest": ("a",)},
        MsgMeta(origin="t", t=1),
    )
    assert line.low is True


def test_typed_watcher_round_trip():
    """A GpioRoot built up via ``set`` keeps the type chain consistent."""
    root = GpioRoot()
    root.set(
        P("myhost.chip0.5"),
        {"type": "input", "mode": "read", "dest": ("a", "b")},
        MsgMeta(origin="t", t=1),
    )
    leaf = root.get(P("myhost.chip0.5"))
    assert isinstance(leaf, GpioLine)
    assert leaf.is_complete()
