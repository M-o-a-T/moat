"""
Test moat.modbus.dev server features.

Tests for register transformation, remapping, const values, and age-based re-reading.
"""

from __future__ import annotations

import anyio
import logging
import pytest

from moat.util import yload
from moat.modbus.client import ModbusClient
from moat.modbus.dev.poll import dev_poll
from moat.modbus.types import HoldingRegisters, IntValue

logger = logging.getLogger(__name__)


@pytest.mark.trio
async def test_transformation_serving(autojump_clock, free_tcp_port_factory):
    """Test that transformations are applied when serving registers.

    This test verifies that when a client reads from a remote device and applies
    transformations (offset/factor), and then serves those values via its own
    Modbus server, the transformed values are served (not the raw values).
    """
    autojump_clock.autojump_threshold = 0.2

    # Create two ports: one for the "remote device", one for the gateway
    remote_port = free_tcp_port_factory()
    gateway_port = free_tcp_port_factory()

    # Remote device config - simulates the actual device
    remote_cfg = yload(
        f"""
server:
  - host: 127.0.0.1
    port: {remote_port}
    units:
      1:
        regs:
          raw_value:
            reg_type: h
            register: 100
            type: uint
            len: 1
""",
        attr=True,
    )

    async with anyio.create_task_group() as tg:
        # Start the remote device
        remote = await tg.start(dev_poll, remote_cfg, None)
        await anyio.sleep(0.1)

        # Set a raw value in the remote device
        remote_reg = remote.server[0].units[1].regs.raw_value
        remote_reg.value = 10

        # Gateway config - reads from remote device with transformation and serves
        gateway_cfg = yload(
            f"""
slots:
  fast:
    read_delay: 0.5

server:
  - host: 127.0.0.1
    port: {gateway_port}

hostports:
  localhost:
    {remote_port}:
      1:
        server: 1
        regs:
          transformed_value:
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

        # Start the gateway (reads from remote, serves transformed)
        gateway = await tg.start(dev_poll, gateway_cfg, None)
        await anyio.sleep(1)  # Let it read

        # Gateway should have read and transformed: (10 * 2) + 42 = 62
        gw_reg = gateway.hostports.localhost[remote_port][1].regs.transformed_value
        assert gw_reg.value == 62

        # Now test serving: read from the gateway's server
        # The gateway should serve the transformed value (62), not raw (10)
        async with (
            ModbusClient() as cli,
            cli.host("localhost", gateway_port) as h,
            h.unit(1) as u,
            u.slot("test") as s,
        ):
            s.add(HoldingRegisters, 100, IntValue)
            res = await s.getValues()
            served_value = res[HoldingRegisters][100].value

            # The gateway should serve the transformed value
            assert served_value == 62, f"Expected 62, got {served_value}"

        tg.cancel_scope.cancel()


@pytest.mark.trio
async def test_register_remapping(autojump_clock, free_tcp_port_factory):
    """Test that registers can be remapped via 'server' parameter.

    Verifies that:
    - A register at address 100 on the remote device can appear at address 200 on the gateway
    - 'server: none' prevents a register from being served
    """
    autojump_clock.autojump_threshold = 0.2

    remote_port = free_tcp_port_factory()
    gateway_port = free_tcp_port_factory()

    # Remote device with two registers
    remote_cfg = yload(
        f"""
server:
  - host: 127.0.0.1
    port: {remote_port}
    units:
      1:
        regs:
          value_a:
            reg_type: h
            register: 100
            type: uint
            len: 1
          value_b:
            reg_type: h
            register: 101
            type: uint
            len: 1
""",
        attr=True,
    )

    async with anyio.create_task_group() as tg:
        # Start remote device
        remote = await tg.start(dev_poll, remote_cfg, None)
        await anyio.sleep(0.1)

        # Set values
        remote.server[0].units[1].regs.value_a.value = 42
        remote.server[0].units[1].regs.value_b.value = 99

        # Gateway config: remap register 100 to 200, hide register 101
        gateway_cfg = yload(
            f"""
slots:
  fast:
    read_delay: 0.5

server:
  - host: 127.0.0.1
    port: {gateway_port}

hostports:
  localhost:
    {remote_port}:
      1:
        server: 1
        regs:
          value_a:
            reg_type: h
            register: 100
            type: uint
            len: 1
            slot: fast
            server: 200
          value_b:
            reg_type: h
            register: 101
            type: uint
            len: 1
            slot: fast
            server: none
""",
            attr=True,
        )

        # Start gateway
        await tg.start(dev_poll, gateway_cfg, None)
        await anyio.sleep(1)  # Let it read

        # Test: Read from gateway server
        async with (
            ModbusClient() as cli,
            cli.host("localhost", gateway_port) as h,
            h.unit(1) as u,
            u.slot("test") as s,
        ):
            # Register 100 should NOT be accessible (it's remapped to 200)
            s.add(HoldingRegisters, 100, IntValue)
            s.add(HoldingRegisters, 101, IntValue)
            s.add(HoldingRegisters, 200, IntValue)
            res = await s.getValues()

            # Register 100 should not exist (remapped to 200)
            assert res[HoldingRegisters][100].value == 0, "Register 100 should be empty/default"

            # Register 101 should not exist (server: none)
            assert res[HoldingRegisters][101].value == 0, "Register 101 should be hidden"

            # Register 200 should have the value from register 100
            assert res[HoldingRegisters][200].value == 42, (
                "Register 200 should have remapped value"
            )

        tg.cancel_scope.cancel()


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
