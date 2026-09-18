"""
Tests for the flexible stream stack builder (:func:`moat.lib.stream.build_stack`).
"""

from __future__ import annotations

import importlib.util
import pytest

from moat.util import attrdict
from moat.lib.micro import Event, TaskGroup
from moat.lib.rpc._test import Loopback
from moat.lib.stream import (
    BaseMsg,
    CBORMsgBlk,
    CBORMsgBuf,
    LogMsg,
    ReliableMsg,
    build_stack,
    serial_stack,
)
from moat.lib.stream.serial import SerialPackerBlkBuf

pytestmark = pytest.mark.anyio

# The framed codec path instantiates ``SerialPackerBlkBuf``, which depends on
# the external ``serialpacker`` package.  Skip those tests when it is absent
# rather than reporting a hard failure.
_has_serialpacker = importlib.util.find_spec("serialpacker") is not None
needs_serialpacker = pytest.mark.skipif(not _has_serialpacker, reason="serialpacker not installed")


def _loopback_pair(qlen: int = 4):
    """Create a linked pair of Loopback streams."""
    u1 = Loopback(qlen=qlen)
    u2 = Loopback(qlen=qlen)
    u1.link(u2)
    u2.link(u1)
    return u1, u2


# ── Implicit mode (auto-detect from config keys) ───────────────────────


async def test_implicit_basic():
    """Minimal implicit stack: just a CBOR codec, no extras."""
    u1, u2 = _loopback_pair()
    cfg = attrdict(link=attrdict())
    s1 = build_stack(u1, cfg)
    s2 = build_stack(u2, cfg)
    assert isinstance(s1, BaseMsg)
    assert isinstance(s2, BaseMsg)
    assert isinstance(s1, CBORMsgBuf)


@needs_serialpacker
async def test_implicit_framed():
    """Implicit mode with frame=dict → framed codec (CBORMsgBlk)."""
    u1, _u2 = _loopback_pair()
    cfg = attrdict(link=attrdict(frame=dict(frame_start=0xFE)))
    s1 = build_stack(u1, cfg)
    assert isinstance(s1, CBORMsgBlk)


async def test_implicit_lossy():
    """Implicit mode with lossy → ReliableMsg on top."""
    u1, _u2 = _loopback_pair()
    cfg = attrdict(
        link=attrdict(lossy=dict(window=4, timeout=100)),
    )
    s1 = build_stack(u1, cfg)
    assert isinstance(s1, ReliableMsg)


async def test_implicit_log():
    """Implicit mode with log → LogMsg on top."""
    u1, _u2 = _loopback_pair()
    cfg = attrdict(
        link=attrdict(),
        log=dict(txt="T"),
    )
    s1 = build_stack(u1, cfg)
    assert isinstance(s1, LogMsg)


async def test_implicit_log_raw():
    """Implicit mode with log_raw → LogMsg at the bottom."""
    u1, _u2 = _loopback_pair()
    cfg = attrdict(
        link=attrdict(),
        log_raw=dict(txt="R"),
    )
    s1 = build_stack(u1, cfg)
    # The outer layer is CBORMsgBuf; the inner is LogMsg wrapping the Loopback.
    assert isinstance(s1, CBORMsgBuf)
    assert isinstance(s1.link, LogMsg)


async def test_implicit_full():
    """Implicit mode with all layers: log_raw + cbor + reliable + log."""
    u1, _u2 = _loopback_pair()
    cfg = attrdict(
        link=attrdict(lossy=dict(window=4, timeout=100)),
        log=dict(txt="H"),
        log_raw=dict(txt="R"),
    )
    s1 = build_stack(u1, cfg)
    # Top → bottom: LogMsg → ReliableMsg → CBORMsgBuf → LogMsg → Loopback
    assert isinstance(s1, LogMsg)
    assert isinstance(s1.link, ReliableMsg)
    assert isinstance(s1.link.link, CBORMsgBuf)
    assert isinstance(s1.link.link.link, LogMsg)


# ── Explicit mode (layers list) ───────────────────────────────────────


async def test_explicit_single():
    """Explicit layers with a single cbor_buf."""
    u1, _u2 = _loopback_pair()
    cfg = attrdict(layers=["cbor_buf"])
    s1 = build_stack(u1, cfg)
    assert isinstance(s1, CBORMsgBuf)


async def test_explicit_multi():
    """Explicit layers: cbor_buf + reliable + log."""
    u1, _u2 = _loopback_pair()
    cfg = attrdict(
        layers=[
            "cbor_buf",
            {"name": "reliable", "cfg": dict(window=4, timeout=100)},
            "log",
        ],
    )
    s1 = build_stack(u1, cfg)
    # Top → bottom: LogMsg → ReliableMsg → CBORMsgBuf
    assert isinstance(s1, LogMsg)
    assert isinstance(s1.link, ReliableMsg)
    assert isinstance(s1.link.link, CBORMsgBuf)


async def test_explicit_unknown_layer():
    """Unknown layer name raises ValueError."""
    u1, _ = _loopback_pair()
    cfg = attrdict(layers=["nonexistent"])
    with pytest.raises(ValueError, match="Unknown stream layer"):
        build_stack(u1, cfg)


# ── Framed parameter ──────────────────────────────────────────────────


@needs_serialpacker
async def test_framed_true():
    """framed=True forces CBORMsgBlk even without frame in config."""
    u1, _ = _loopback_pair()
    cfg = attrdict(link=attrdict())
    s1 = build_stack(u1, cfg, framed=True)
    assert isinstance(s1, CBORMsgBlk)


async def test_framed_false():
    """framed=False forces CBORMsgBuf even if frame is a dict."""
    u1, _ = _loopback_pair()
    cfg = attrdict(link=attrdict(frame=dict(frame_start=0xFE)))
    s1 = build_stack(u1, cfg, framed=False)
    assert isinstance(s1, CBORMsgBuf)


# ── Backward compatibility: serial_stack delegates to build_stack ──────


async def test_serial_stack_delegates():
    """serial_stack produces the same result as build_stack."""
    u1, _u2 = _loopback_pair()
    cfg = attrdict(link=attrdict())
    s1 = serial_stack(u1, cfg)
    assert isinstance(s1, CBORMsgBuf)


@needs_serialpacker
async def test_serial_stack_framed():
    """serial_stack with frame=dict produces CBORMsgBlk."""
    u1, _ = _loopback_pair()
    cfg = attrdict(link=attrdict(frame=dict(frame_start=0xFE)))
    s1 = serial_stack(u1, cfg)
    assert isinstance(s1, CBORMsgBlk)


# ── Functional round-trip test ────────────────────────────────────────


async def test_roundtrip_implicit():
    """Messages survive a round-trip through an implicitly-built stack."""
    u1, u2 = _loopback_pair()
    cfg = attrdict(link=attrdict())
    s1 = build_stack(u1, cfg)
    s2 = build_stack(u2, cfg)

    msg = dict(hello="world", n=42)
    recv = {}
    done = Event()

    async def sender():
        await s1.send(msg)

    async def receiver():
        recv["m"] = await s2.recv()
        done.set()

    async with TaskGroup() as tg, s1, s2:
        tg.start_soon(receiver)
        tg.start_soon(sender)
        await done.wait()

    assert recv["m"] == msg


async def test_roundtrip_explicit():
    """Messages survive a round-trip through an explicitly-built stack."""
    u1, u2 = _loopback_pair()
    cfg = attrdict(layers=["cbor_buf"])
    s1 = build_stack(u1, cfg)
    s2 = build_stack(u2, cfg)

    msg = dict(test=True, data=[1, 2, 3])
    recv = {}
    done = Event()

    async def sender():
        await s1.send(msg)

    async def receiver():
        recv["m"] = await s2.recv()
        done.set()

    async with TaskGroup() as tg, s1, s2:
        tg.start_soon(receiver)
        tg.start_soon(sender)
        await done.wait()

    assert recv["m"] == msg


@needs_serialpacker
async def test_roundtrip_framed():
    """Framed stack structure is correct (CBORMsgBlk over SerialPackerBlkBuf)."""
    u1, u2 = _loopback_pair()
    cfg = attrdict(link=attrdict(frame=dict(frame_start=0xFE)))
    s1 = build_stack(u1, cfg)
    s2 = build_stack(u2, cfg)

    # Top → bottom: CBORMsgBlk → SerialPackerBlkBuf → Loopback
    assert isinstance(s1, CBORMsgBlk)
    assert isinstance(s1.link, SerialPackerBlkBuf)
    assert isinstance(s2, CBORMsgBlk)
    assert isinstance(s2.link, SerialPackerBlkBuf)
