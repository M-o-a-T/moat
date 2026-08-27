"""
Test the fake pin implementation.

The FakePin (_fake.Pin / moat.micro.part.fake.Pin) is a software-only
digital pin used for testing. It supports:
- Basic get/set via SDP
- in_value() for unconditional setting
- Event-based change notification
- Stream protocol
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.micro import sleep_ms
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack
from moat.micro.app._fake import PINS

CFG = """
app: dir
p:
  app: _fake.Pin
  pin: X
"""

CFG_INIT = """
app: dir
p:
  app: _fake.Pin
  pin: Y
  init: true
"""


@pytest.mark.anyio
async def test_fpk_basic(tmp_path):
    """Basic SDP get/set on a fake pin."""
    async with rpc_stack(tmp_path, CFG) as d:
        p = d.sub_at(P("p"))

        # Default value is False
        assert False is await p()

        # Set True
        await p(True)
        assert True is await p()

        # Set False
        await p(False)
        assert False is await p()


@pytest.mark.anyio
async def test_fpk_init(tmp_path):
    """Fake pin with init=true starts True."""
    async with rpc_stack(tmp_path, CFG_INIT) as d:
        p = d.sub_at(P("p"))
        ph = d.app.sub["p"]

        assert True is ph.value
        assert True is await p()


@pytest.mark.anyio
async def test_fpk_in_value(tmp_path):
    """in_value sets the pin unconditionally and triggers the Event."""
    async with rpc_stack(tmp_path, CFG) as d:
        p = d.sub_at(P("p"))
        ph = d.app.sub["p"]

        assert False is ph.value

        # in_value sets directly
        ph.in_value(True)
        assert True is ph.value
        assert True is await p()

        ph.in_value(False)
        assert False is ph.value
        assert False is await p()


@pytest.mark.anyio
async def test_fpk_get(tmp_path):
    """get() waits for the next value change."""
    async with rpc_stack(tmp_path, CFG) as d:
        ph = d.app.sub["p"]

        # Schedule a value change after a short delay
        async def changer():
            await sleep_ms(20)
            ph.in_value(True)

        async with anyio.create_task_group() as tg:
            tg.start_soon(changer)
            val = await ph.get()
            assert val is True

        assert True is ph.value


@pytest.mark.anyio
async def test_fpk_value_property(tmp_path):
    """The value property returns the current state."""
    async with rpc_stack(tmp_path, CFG) as d:
        ph = d.app.sub["p"]

        assert False is ph.value
        ph.in_value(True)
        assert True is ph.value
        ph.in_value(False)
        assert False is ph.value


@pytest.mark.anyio
async def test_fpk_sdp_roundtrip(tmp_path):
    """SDP cmd() with no args reads, with arg writes."""
    async with rpc_stack(tmp_path, CFG) as d:
        p = d.sub_at(P("p"))
        ph = d.app.sub["p"]

        # Read via SDP
        assert False is await p()

        # Write via SDP
        await p(True)
        assert True is ph.value
        assert True is await p()

        await p(False)
        assert False is ph.value
        assert False is await p()


@pytest.mark.anyio
async def test_fpk_multiple_changes(tmp_path):
    """Multiple rapid changes all register."""
    async with rpc_stack(tmp_path, CFG) as d:
        p = d.sub_at(P("p"))
        ph = d.app.sub["p"]

        for i in range(5):
            ph.in_value(bool(i % 2))
            assert bool(i % 2) is ph.value

        # Final state matches last set
        assert False is ph.value  # i=4, 4%2=0
        assert False is await p()


@pytest.mark.anyio
async def test_fpk_pins_registry(tmp_path):
    """Fake pins register in the PINS dict."""
    async with rpc_stack(tmp_path, CFG) as d:
        ph = d.app.sub["p"]

        # The pin should be in PINS
        assert "X" in PINS
        assert PINS["X"] is ph
