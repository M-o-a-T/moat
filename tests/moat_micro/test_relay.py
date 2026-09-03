"""
Test the relay implementation.

Covers: basic state, force/delay, min-on/off timers, get/get_sync,
delayed property, SDP cmd, cmd_r state reporting, reload.
"""

from __future__ import annotations

import pytest

from moat.lib.micro import sleep_ms
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack

CFG = """
app: dir
r:
  app: part.Relay
  pin: !P p
  t:
    on: 50
    off: 150
p:
  app: _fake.Pin
  pin: X
"""

CFG_NOTIME = """
app: dir
r:
  app: part.Relay
  pin: !P p
p:
  app: _fake.Pin
  pin: X
"""


@pytest.mark.anyio
async def test_rly(tmp_path):
    """fake relay test"""
    async with rpc_stack(tmp_path, CFG) as d:
        r = d.sub_at(P("r"))
        p = d.sub_at(P("p"))

        # this starts the min-on timer 50.
        await p(True)
        await r.w(v=True)
        assert True is await p()

        await r.w(f=False)
        # this kills the previous timer and starts a min-off-timer 150.

        assert False is await p()
        await r.w(v=True, f=None)  # X
        assert False is await p()
        await sleep_ms(100)
        assert False is await p()
        # the off timer runs out after 150, i.e. sometime during the next
        # sleep, and the (X) turns the relay on and starts a new
        # min-on-timer 50.
        await sleep_ms(80)
        assert True is await p()
        await r.w(False)
        # the min-on timer has ~20 msec remaining at this point, thus the
        # pin is still on.
        assert True is await p()
        await sleep_ms(40)
        # Now it is not.
        assert False is await p()


@pytest.mark.anyio
async def test_rly_force(tmp_path):
    """Force overrides the value."""
    async with rpc_stack(tmp_path, CFG) as d:
        r = d.sub_at(P("r"))
        p = d.sub_at(P("p"))
        rh = d.app.sub["r"]

        # Turn on
        await r.w(v=True)
        assert True is await p()

        # Force off — overrides value
        await r.w(f=False)
        assert False is await p()

        # Value is still True internally, but force keeps it off
        assert True is rh.value
        assert False is rh.force

        # Release force → pin returns to value (after min-off timer)
        await r.w(f=None)
        # Min-off timer (150ms) is running, so pin stays off
        assert False is await p()
        await sleep_ms(180)
        assert True is await p()


@pytest.mark.anyio
async def test_rly_force_on(tmp_path):
    """Force on overrides an off value."""
    async with rpc_stack(tmp_path, CFG) as d:
        r = d.sub_at(P("r"))
        p = d.sub_at(P("p"))

        await r.w(v=False)
        assert False is await p()

        # Force on
        await r.w(f=True)
        assert True is await p()

        # Release force → returns to value (False), min-on timer runs
        await r.w(f=None)
        # Min-on timer keeps it on briefly
        assert True is await p()
        await sleep_ms(80)
        assert False is await p()


@pytest.mark.anyio
async def test_rly_notime(tmp_path):
    """Relay without timing constraints switches instantly."""
    async with rpc_stack(tmp_path, CFG_NOTIME) as d:
        r = d.sub_at(P("r"))
        p = d.sub_at(P("p"))
        rh = d.app.sub["r"]

        await r.w(v=True)
        assert True is await p()

        await r.w(v=False)
        assert False is await p()

        await r.w(v=True)
        assert True is await p()

        # No delay
        assert not rh.delayed


@pytest.mark.anyio
async def test_rly_get(tmp_path):
    """get/get_sync return the intended state."""
    async with rpc_stack(tmp_path, CFG) as d:
        r = d.sub_at(P("r"))
        rh = d.app.sub["r"]

        await r.w(v=True)
        assert True is await rh.get()
        assert True is rh.get_sync()

        await r.w(v=False)
        assert False is await rh.get()
        assert False is rh.get_sync()

        # Force changes what get returns
        await r.w(f=True)
        assert True is await rh.get()
        assert True is rh.get_sync()


@pytest.mark.anyio
async def test_rly_delayed(tmp_path):
    """The 'delayed' property reflects timer state."""
    async with rpc_stack(tmp_path, CFG) as d:
        r = d.sub_at(P("r"))
        rh = d.app.sub["r"]

        # Pin starts at False (default). Set relay to True → pin changes → timer starts
        await r.w(v=True)
        # Min-on timer (50ms) is running
        assert rh.delayed

        await sleep_ms(80)
        # Timer expired
        assert not rh.delayed

        await r.w(v=False)
        # Min-off timer (150ms) is running
        assert rh.delayed

        await sleep_ms(180)
        assert not rh.delayed


@pytest.mark.anyio
async def test_rly_cmd_r(tmp_path):
    """cmd_r returns the full state mapping."""
    async with rpc_stack(tmp_path, CFG) as d:
        r = d.sub_at(P("r"))

        # Pin starts at False. Set relay True → pin changes → min-on timer starts
        await r.w(v=True)

        state = await r.r()
        assert state["v"] is True
        assert state["f"] is None
        assert state["p"] is True
        assert state["d"] is not None  # delay is running (min-on 50ms)

        await sleep_ms(80)
        state = await r.r()
        assert state["d"] is None  # delay expired


@pytest.mark.anyio
async def test_rly_sdp(tmp_path):
    """SDP cmd() get/set works."""
    async with rpc_stack(tmp_path, CFG_NOTIME) as d:
        r = d.sub_at(P("r"))
        p = d.sub_at(P("p"))

        # SDP set
        await r(True)
        assert True is await r()  # SDP get returns value
        assert True is await p()

        # SDP set to False
        await r(False)
        assert False is await r()
        assert False is await p()


@pytest.mark.anyio
async def test_rly_sdp_with_delay(tmp_path):
    """SDP respects min-on/off delays."""
    async with rpc_stack(tmp_path, CFG) as d:
        r = d.sub_at(P("r"))
        p = d.sub_at(P("p"))

        # Pin starts at False. SDP set True → pin changes → min-on timer starts
        await r(True)
        assert True is await p()

        # Wait for min-on timer (50ms) to expire
        await sleep_ms(80)

        # SDP set False → pin changes → min-off timer starts
        await r(False)
        assert False is await p()

        # SDP set True while min-off timer running → delayed, pin stays False
        await r(True)
        assert False is await p()
        await sleep_ms(180)
        assert True is await p()


@pytest.mark.anyio
async def test_rly_reload(tmp_path):
    """Reload updates timing parameters."""
    async with rpc_stack(tmp_path, CFG) as d:
        r = d.sub_at(P("r"))
        rh = d.app.sub["r"]

        # Original timing: on=50, off=150
        # Pin starts at False. Set relay True → pin changes → min-on timer starts
        await r.w(v=True)
        assert rh.delayed  # min-on timer running

        await sleep_ms(80)
        assert not rh.delayed  # timer expired

        # Reload with new timings
        rh.cfg["t"] = {"on": 200, "off": 300}
        await rh.reload()

        await r.w(v=False)
        assert rh.delayed  # min-off timer (300ms) running
        await sleep_ms(250)
        assert rh.delayed  # still running
        await sleep_ms(100)
        assert not rh.delayed  # expired


@pytest.mark.anyio
async def test_rly_init_value(tmp_path):
    """Relay initializes with value=None, pin untouched."""
    async with rpc_stack(tmp_path, CFG_NOTIME) as d:
        r = d.sub_at(P("r"))
        p = d.sub_at(P("p"))
        rh = d.app.sub["r"]

        # Initially value is None, pin is whatever it was set to
        assert rh.value is None
        assert rh.force is None

        # Setting value to True activates the relay
        await r.w(v=True)
        assert True is await p()
        assert rh.value is True


@pytest.mark.anyio
async def test_rly_force_priority(tmp_path):
    """Force takes priority over value in all cases."""
    async with rpc_stack(tmp_path, CFG_NOTIME) as d:
        r = d.sub_at(P("r"))
        p = d.sub_at(P("p"))

        # Set value True
        await r.w(v=True)
        assert True is await p()

        # Force False — pin follows force, not value
        await r.w(f=False)
        assert False is await p()

        # Change value while forced — pin stays at force
        await r.w(v=True)
        assert False is await p()  # still forced off

        # Release force — pin returns to value
        await r.w(f=None)
        assert True is await p()
