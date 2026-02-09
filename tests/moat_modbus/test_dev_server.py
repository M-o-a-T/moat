"""
Test moat.modbus.dev server features.

Tests for register transformation, remapping, const values, and age-based re-reading.
"""

from __future__ import annotations

import anyio
import logging
import pytest

from moat.util import yload
from moat.modbus.dev.poll import dev_poll

logger = logging.getLogger(__name__)


@pytest.mark.trio
async def test_transformation_serving(autojump_clock, free_tcp_port):
    """Test that transformations are applied when serving registers."""
    autojump_clock.autojump_threshold = 0.2

    # Server config - creates a simple Modbus device
    srv_cfg = yload(
        f"""
server:
  - host: 127.0.0.1
    port: {free_tcp_port}
    units:
      1:
        regs:
          test_value:
            reg_type: h
            register: 100
            type: uint
            len: 1
""",
        attr=True,
    )

    async with anyio.create_task_group() as tg:
        # Start the server (device to be read from)
        srv = await tg.start(dev_poll, srv_cfg, None)
        await anyio.sleep(0.1)

        # Set a value in the server
        srv_reg = srv.server[0].units[1].regs.test_value
        srv_reg.value = 10

        # Client config - connects and reads with transformation
        cli_cfg = yload(
            f"""
slots:
  fast:
    read_delay: 0.5

hostports:
  localhost:
    {free_tcp_port}:
      1:
        regs:
          test_value:
            reg_type: h
            register: 100
            type: uint
            len: 1
            slot: fast
            offset: 42
            factor: 2
""",
            attr=True,
        )

        # Start the client (reads from server)
        cli = await tg.start(dev_poll, cli_cfg, None)
        await anyio.sleep(1)  # Let it read

        # Client should have read and transformed: (10 * 2) + 42 = 62
        cli_reg = cli.hostports.localhost[free_tcp_port][1].regs.test_value
        assert cli_reg.value == 62

        # Now test serving: when we read from the client's server unit,
        # it should serve the transformed value
        # TODO: Implement this once we have server-side transformation working

        tg.cancel_scope.cancel()


@pytest.mark.trio
async def test_register_remapping(autojump_clock):
    """Test that registers can be remapped via 'server' parameter."""
    # TODO: Implement test for register remapping
    # Original register 100 should appear as register 200 in server
    pass


@pytest.mark.trio
async def test_forward_parameter(autojump_clock):
    """Test that 'forward' parameter controls transparent forwarding."""
    # TODO: Implement test
    # With forward=false, only configured registers should be accessible
    # With forward=true, all registers should be accessible
    pass


@pytest.mark.trio
async def test_const_scalar(autojump_clock):
    """Test serving constant scalar values."""
    # TODO: Implement test
    # Register with const: 42 should always return 42
    pass


@pytest.mark.trio
async def test_const_mqtt(cfg, autojump_clock):
    """Test serving values from MQTT via const: !P path."""
    # TODO: Implement test
    # Register with const: !P topic.path should serve current MQTT value
    pass


@pytest.mark.trio
async def test_age_based_rereading(cfg, autojump_clock):
    """Test age-based slot re-reading."""
    # TODO: Implement test
    # When data is older than slot's age parameter, should trigger re-read
    # Re-read should not forward to MQTT
    pass
