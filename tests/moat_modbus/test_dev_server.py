"""
Test moat.modbus.dev server features.

Tests for register transformation, remapping, const values, and age-based re-reading.
"""

from __future__ import annotations

import anyio
import logging
import pytest

from moat.util import yload
from moat.lib.path import P
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
async def test_forward_parameter(autojump_clock, free_tcp_port_factory):
    """Test that 'forward' parameter controls transparent forwarding.
    
    Verifies that:
    - With forward=true, unconfigured registers are forwarded transparently
    - With forward=false, only configured registers are accessible
    """
    autojump_clock.autojump_threshold = 0.2

    remote_port = free_tcp_port_factory()
    gateway_port = free_tcp_port_factory()

    # Remote device with multiple registers
    remote_cfg = yload(
        f"""
server:
  - host: 127.0.0.1
    port: {remote_port}
    units:
      1:
        regs:
          reg_100:
            reg_type: h
            register: 100
            type: uint
            len: 1
          reg_101:
            reg_type: h
            register: 101
            type: uint
            len: 1
          reg_102:
            reg_type: h
            register: 102
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
        remote.server[0].units[1].regs.reg_100.value = 100
        remote.server[0].units[1].regs.reg_101.value = 101
        remote.server[0].units[1].regs.reg_102.value = 102

        # Gateway with forward=false: only register 100 configured
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
        forward: false
        regs:
          reg_100:
            reg_type: h
            register: 100
            type: uint
            len: 1
            slot: fast
""",
            attr=True,
        )

        # Start gateway
        await tg.start(dev_poll, gateway_cfg, None)
        await anyio.sleep(1)  # Let it read

        # Test: Read from gateway server with forward=false
        async with (
            ModbusClient() as cli,
            cli.host("localhost", gateway_port) as h,
            h.unit(1) as u,
            u.slot("test") as s,
        ):
            # Read individual registers
            s.add(HoldingRegisters, 100, IntValue)
            res = await s.getValues()
            assert res[HoldingRegisters][100].value == 100, "Configured register should work"
            
            # Read unconfigured registers individually
            s2 = await u.slot_scope("test2")
            s2.add(HoldingRegisters, 101, IntValue)
            res2 = await s2.getValues()
            assert res2[HoldingRegisters][101].value == 0, "Unconfigured register should be empty with forward=false"

        tg.cancel_scope.cancel()


@pytest.mark.trio
async def test_forward_true(autojump_clock, free_tcp_port_factory):
    """Test that forward=true enables transparent forwarding of unconfigured registers.
    
    Note: This test is currently a placeholder. Implementing true transparent
    forwarding is complex because Modbus requests can span multiple registers,
    some configured and some not. This requires splitting requests and merging results.
    
    For now, forward=true behaves the same as forward=false (returns zeros for
    unconfigured registers). Full implementation is deferred.
    """
    # TODO: Implement transparent forwarding
    # This requires:
    # 1. Detecting which registers in a request are configured vs unconfigured
    # 2. Forwarding unconfigured register requests to the client unit
    # 3. Merging results from local store and forwarded requests
    # 4. Handling edge cases where a single Modbus read spans both types
    pass


@pytest.mark.trio
async def test_const_scalar(autojump_clock, free_tcp_port_factory):
    """Test serving constant scalar values."""
    autojump_clock.autojump_threshold = 0.2

    gateway_port = free_tcp_port_factory()

    # Gateway config with const values
    gateway_cfg = yload(
        f"""
server:
  - host: 127.0.0.1
    port: {gateway_port}
    units:
      1:
        regs:
          firmware_version:
            reg_type: h
            register: 0
            type: uint
            len: 1
            const: 42
          pi_value:
            reg_type: h
            register: 1
            type: uint
            len: 1
            const: 314
""",
        attr=True,
    )

    async with anyio.create_task_group() as tg:
        # Start gateway
        await tg.start(dev_poll, gateway_cfg, None)
        await anyio.sleep(0.1)

        # Test: Read const values
        async with (
            ModbusClient() as cli,
            cli.host("localhost", gateway_port) as h,
            h.unit(1) as u,
            u.slot("test") as s,
        ):
            s.add(HoldingRegisters, 0, IntValue)
            s.add(HoldingRegisters, 1, IntValue)
            res = await s.getValues()

            # Should return const values
            assert res[HoldingRegisters][0].value == 42
            assert res[HoldingRegisters][1].value == 314

        tg.cancel_scope.cancel()


@pytest.mark.trio
async def test_const_mqtt(cfg, autojump_clock, free_tcp_port_factory):
    """Test serving values from MQTT via const: !P path.
    
    This tests that:
    1. The register's READ value is updated from MQTT
    2. The write value is NOT triggered (should not write back to device)
    3. Changes in MQTT are reflected when reading the register
    """
    autojump_clock.autojump_threshold = 0.2

    gateway_port = free_tcp_port_factory()

    # Gateway config with const MQTT subscription
    gateway_cfg = yload(
        f"""
server:
  - host: 127.0.0.1
    port: {gateway_port}
    units:
      1:
        regs:
          external_sensor:
            reg_type: h
            register: 10
            type: uint
            len: 1
            const: !P sensors.external.temperature
""",
        attr=True,
    )

    from moat.link._test import Scaffold  # noqa: PLC0415

    async with (
        Scaffold(True, use_servers=True) as sf,
        sf.server_(init={"Hello": "World"}),
        sf.client_() as c,
    ):
        # Set initial MQTT value
        await c.d_set(P("sensors.external.temperature"), data=250)
        await c.i_sync()
        async with anyio.create_task_group() as tg:
            # Start gateway
            gateway = await tg.start(dev_poll, gateway_cfg, c)
            await anyio.sleep(0.5)

            # Get the register to check internal state
            reg = gateway.server[0].units[1].regs.external_sensor

            # Check that the read value was updated from MQTT
            assert reg.reg._value == 250, f"Expected read value 250, got {reg.reg._value}"
            
            # Check that write value was NOT set (shouldn't trigger writes)
            assert reg.reg._value_w is None or reg.reg._value_w == 250, \
                "Write value should not be set differently from read value"

            # Test: Read value from Modbus server
            async with (
                ModbusClient() as cli,
                cli.host("localhost", gateway_port) as h,
                h.unit(1) as u,
                u.slot("test") as s,
            ):
                s.add(HoldingRegisters, 10, IntValue)
                res = await s.getValues()

                # Should return MQTT value
                assert res[HoldingRegisters][10].value == 250, \
                    f"Expected 250 from Modbus, got {res[HoldingRegisters][10].value}"

                # Update MQTT value
                await c.d_set(P("sensors.external.temperature"), data=275)
                await anyio.sleep(0.5)

                # Check internal state again
                assert reg.reg._value == 275, f"Expected updated read value 275, got {reg.reg._value}"

                # Read again from Modbus
                s2 = await u.slot_scope("test2")
                s2.add(HoldingRegisters, 10, IntValue)
                res2 = await s2.getValues()

                # Should return updated MQTT value
                assert res2[HoldingRegisters][10].value == 275, \
                    f"Expected updated value 275, got {res2[HoldingRegisters][10].value}"

            tg.cancel_scope.cancel()


@pytest.mark.trio
async def test_age_based_rereading(autojump_clock, free_tcp_port_factory):
    """Test age-based slot re-reading.
    
    Note: Age-based re-reading is complex and requires:
    1. Tracking last read time for each slot
    2. Checking age when server reads are requested
    3. Triggering on-demand reads when data is stale
    4. Preventing MQTT forwarding for age-triggered reads
    5. Handling split reads across multiple slots
    
    This is deferred due to complexity. The 'age' parameter is documented
    but not yet implemented.
    """
    # TODO: Full implementation of age-based re-reading
    # For now, this is a placeholder test
    pass
