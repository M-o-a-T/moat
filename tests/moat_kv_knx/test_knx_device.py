"""
End-to-end integration tests for moat.kv.knx with moat acting as the device side.

The full stack under test is::

    xknx Switch (controller, on xknx_monitor)
        └─ knxd (dummy driver + KNXnet/IP tunneling)
            └─ XKNX-A (moat side, created by task())
                └─ KNXroot
                    ├─ type=in  at 0/0/1  →  moat-kv path ``test.cmd``
                    └─ type=out at 0/0/2  ←  moat-kv path ``test.state``
                └─ moat-kv (stdtest in-process server)

This is the inverse of ``test_knx_act.py`` (where moat-kv-knx acts as the
controller and a :class:`~moat.kv.knx.mock.SimulatedBinaryDevice` acts as
the KNX device).  Here the xknx :class:`~xknx.devices.Switch` is the bus
peer and moat-kv-knx provides the bidirectional bridge:

- **Direction 1 — controller → moat-kv**: the Switch sends a
  ``GroupValueWrite`` command on the command address (0/0/1).  The
  ``type=in`` node receives it and writes the boolean value to ``test.cmd``
  in moat-kv.

- **Direction 2 — moat-kv → controller**: a moat-kv write to ``test.state``
  causes the ``type=out`` node to send a ``GroupValueWrite`` on the state
  address (0/0/2).  The Switch receives it on its ``group_address_state`` and
  updates its internal state.

This file covers moat-b0q (kv-to-device binary roundtrip, device side).
"""

from __future__ import annotations

import anyio
import pytest

from xknx.devices import BinarySensor, Switch
from xknx.dpt import DPTBinary
from xknx.telegram import GroupAddress, Telegram
from xknx.telegram.apci import GroupValueWrite

from moat.util import attrdict
from moat.kv.knx.model import KNXroot
from moat.kv.knx.task import task
from moat.kv.mock.mqtt import stdtest
from moat.lib.path import P, Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xknx

pytestmark = pytest.mark.anyio

# ── Fixed addresses and path names ────────────────────────────────────────── #

_PREFIX = P(":.moat.kv.knx")
_KV_CMD = P("test.cmd")  # written by type=in when Switch sends a command
_KV_STATE = P("test.state")  # watched by type=out; Switch receives changes
_CMD_ADDR = GroupAddress("0/0/1")  # Switch sends here; moat type=in listens
_STATE_ADDR = GroupAddress("0/0/2")  # moat type=out sends here; Switch listens
_SENSOR_ADDR = GroupAddress("0/0/3")  # moat type=out acts as sensor; BinarySensor listens
_KV_SENSOR = P("test.sensor")  # moat-kv path watched by the sensor type=out node
_BUS = "testbus"
_SRV = "myserver"


async def test_binary_roundtrip(
    knxd_port: int,
    xknx_monitor: xknx.XKNX,
) -> None:
    """
    Verify the full two-way binary roundtrip with moat-kv-knx as the device.

    **Direction 1 — controller → moat-kv**:
    :meth:`~xknx.devices.Switch.set_on` / :meth:`~xknx.devices.Switch.set_off`
    on the xknx Switch sends a ``GroupValueWrite`` on the command address
    (0/0/1).  The ``type=in`` node receives it and writes the boolean value
    to ``test.cmd``.

    **Direction 2 — moat-kv → controller**: a write to ``test.state`` causes
    the ``type=out`` node to send a ``GroupValueWrite`` on the state address
    (0/0/2).  The Switch receives it on its ``group_address_state`` and
    updates its internal state.

    Args:
        knxd_port: Port of the running knxd instance (from fixture).
        xknx_monitor: Connected XKNX instance hosting the Switch controller
            (from fixture).
    """
    cfg = attrdict(prefix=_PREFIX, server_default=attrdict(port=3671))

    # ── Switch controller on xknx_monitor ─────────────────────────────────── #
    # sync_state=False: suppress the startup GroupValueRead on 0/0/2 that
    # would otherwise pre-populate sw_recv with a spurious callback.
    switch = Switch(
        xknx_monitor,
        "TestSwitch",
        group_address=_CMD_ADDR,
        group_address_state=_STATE_ADDR,
        sync_state=False,
    )
    xknx_monitor.devices.async_add(switch)

    # Collect every Switch device_updated_cb in order (fires for both local
    # outgoing processing and incoming state-address telegrams).
    sw_send, sw_recv = anyio.create_memory_object_stream[bool | None](max_buffer_size=16)

    def _on_switch(sw: Switch) -> None:
        if sw.state is not None:
            sw_send.send_nowait(sw.state)

    switch.register_device_updated_cb(_on_switch)

    # Collect GroupValueWrite telegrams arriving on the state address at
    # xknx_monitor (sent by moat's type=out node when test.state changes).
    st_send, st_recv = anyio.create_memory_object_stream[Telegram](max_buffer_size=16)

    def _on_state(tg: Telegram) -> None:
        if isinstance(tg.payload, GroupValueWrite):
            st_send.send_nowait(tg)

    xknx_monitor.telegram_queue.register_telegram_received_cb(
        _on_state, group_addresses=[_STATE_ADDR]
    )

    async with stdtest(args={"init": 0}, tocks=50) as st:
        assert st is not None
        async with st.client() as c:
            # ── Populate the moat-kv KNX configuration tree ─────────────── #

            # Server entry: tells task() where knxd is.
            await c.set(
                _PREFIX + Path.build((_BUS, _SRV)),
                value={"host": "127.0.0.1", "port": knxd_port},
            )
            # type=in: Switch commands on 0/0/1 → writes test.cmd in moat-kv.
            await c.set(
                _PREFIX + Path.build((_BUS, 0, 0, 1)),
                value={"type": "in", "mode": "binary", "dest": _KV_CMD},
            )
            # type=out: test.state changes in moat-kv → sends to 0/0/2 on bus.
            await c.set(
                _PREFIX + Path.build((_BUS, 0, 0, 2)),
                value={"type": "out", "mode": "binary", "src": _KV_STATE},
            )

            # ── Load KNX model and start the moat-kv-knx task ───────────── #

            knxroot = await KNXroot.as_handler(c, cfg=cfg)
            await knxroot.wait_loaded()

            task_ready = anyio.Event()

            # Watch test.cmd for values written by the type=in node.
            cmd_send, cmd_recv = anyio.create_memory_object_stream[bool](max_buffer_size=16)

            async with anyio.create_task_group() as tg:
                tg.start_soon(task, c, cfg, knxroot[_BUS][_SRV], task_ready)

                with anyio.fail_after(10):
                    await task_ready.wait()

                async def _watch_cmd(
                    *, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED
                ) -> None:
                    async with c.watch(_KV_CMD, min_depth=0, max_depth=0) as wp:
                        task_status.started()
                        async for msg in wp:
                            if "path" in msg and "value" in msg:
                                cmd_send.send_nowait(bool(msg.value))

                await tg.start(_watch_cmd)

                # ---------------------------------------------------------- #
                # Direction 1: Switch.set_on() → bus → moat type=in → test.cmd
                # ---------------------------------------------------------- #

                await switch.set_on()

                with anyio.fail_after(5):
                    val = await cmd_recv.receive()
                assert val is True

                # Drain sw_recv: xknx fires device_updated_cb on local outgoing
                # processing too (one True here for the set_on command).
                with anyio.move_on_after(0.5):
                    async for _ in sw_recv:
                        pass

                await switch.set_off()

                with anyio.fail_after(5):
                    val = await cmd_recv.receive()
                assert val is False

                with anyio.move_on_after(0.5):
                    async for _ in sw_recv:
                        pass

                # ---------------------------------------------------------- #
                # Direction 2: test.state → moat type=out → bus → Switch      #
                # ---------------------------------------------------------- #

                await c.set(_KV_STATE, value=True)

                # st_recv fires when the GroupValueWrite on 0/0/2 arrives at
                # xknx_monitor (inside process_telegram_incoming, before
                # devices.process).  By the time the test coroutine resumes,
                # devices.process has already run and sw_recv has data too.
                with anyio.fail_after(5):
                    confirmation = await st_recv.receive()

                assert isinstance(confirmation.payload, GroupValueWrite)
                assert confirmation.payload.value == DPTBinary(1)

                with anyio.fail_after(5):
                    sw_val = await sw_recv.receive()
                assert sw_val is True

                await c.set(_KV_STATE, value=False)

                with anyio.fail_after(5):
                    confirmation = await st_recv.receive()

                assert isinstance(confirmation.payload, GroupValueWrite)
                assert confirmation.payload.value == DPTBinary(0)

                with anyio.fail_after(5):
                    sw_val = await sw_recv.receive()
                assert sw_val is False

                tg.cancel_scope.cancel()


async def test_binary_sensor(
    knxd_port: int,
    xknx_monitor: xknx.XKNX,
) -> None:
    """
    Verify that moat-kv-knx correctly acts as a binary sensor on the bus.

    A moat-kv ``type=out`` node on the sensor address (0/0/3) publishes
    boolean state to the bus whenever ``test.sensor`` changes in moat-kv.
    An xknx :class:`~xknx.devices.BinarySensor` (``group_address_state`` =
    0/0/3) on ``xknx_monitor`` receives each ``GroupValueWrite`` and updates
    its own state.

    ``sync_state=False`` on the :class:`~xknx.devices.BinarySensor` suppresses
    the automatic startup ``GroupValueRead`` that would otherwise send an
    extra telegram before any explicit moat-kv write.

    Args:
        knxd_port: Port of the running knxd instance (from fixture).
        xknx_monitor: Connected XKNX instance hosting the BinarySensor
            controller (from fixture).
    """
    cfg = attrdict(prefix=_PREFIX, server_default=attrdict(port=3671))

    # BinarySensor on xknx_monitor: receives state published by moat type=out.
    # sync_state=False: no startup GroupValueRead, keeping the streams clean.
    bs = BinarySensor(
        xknx_monitor,
        "TestSensor",
        group_address_state=_SENSOR_ADDR,
        sync_state=False,
    )
    xknx_monitor.devices.async_add(bs)

    # Collect BinarySensor device_updated_cb calls (fires after devices.process).
    sens_send, sens_recv = anyio.create_memory_object_stream[bool | None](max_buffer_size=16)

    def _on_sensor(s: BinarySensor) -> None:
        if s.state is not None:
            sens_send.send_nowait(s.state)

    bs.register_device_updated_cb(_on_sensor)

    # Collect GroupValueWrite telegrams on the sensor address at xknx_monitor
    # (sent by moat's type=out node when test.sensor changes).
    st_send, st_recv = anyio.create_memory_object_stream[Telegram](max_buffer_size=16)

    def _on_state(tg: Telegram) -> None:
        if isinstance(tg.payload, GroupValueWrite):
            st_send.send_nowait(tg)

    xknx_monitor.telegram_queue.register_telegram_received_cb(
        _on_state, group_addresses=[_SENSOR_ADDR]
    )

    async with stdtest(args={"init": 0}, tocks=50) as st:
        assert st is not None
        async with st.client() as c:
            await c.set(
                _PREFIX + Path.build((_BUS, _SRV)),
                value={"host": "127.0.0.1", "port": knxd_port},
            )
            # type=out: test.sensor changes → GroupValueWrite on 0/0/3
            await c.set(
                _PREFIX + Path.build((_BUS, 0, 0, 3)),
                value={"type": "out", "mode": "binary", "src": _KV_SENSOR},
            )

            knxroot = await KNXroot.as_handler(c, cfg=cfg)
            await knxroot.wait_loaded()

            task_ready = anyio.Event()

            async with anyio.create_task_group() as tg:
                tg.start_soon(task, c, cfg, knxroot[_BUS][_SRV], task_ready)

                with anyio.fail_after(10):
                    await task_ready.wait()

                # test.sensor=True → GroupValueWrite(1) on 0/0/3 → BinarySensor.state=True
                await c.set(_KV_SENSOR, value=True)

                # st_recv and sens_recv are both populated in the same asyncio
                # iteration (telegram_received_cb fires before devices.process,
                # but both complete before the event loop yields to us).
                with anyio.fail_after(5):
                    confirmation = await st_recv.receive()
                assert isinstance(confirmation.payload, GroupValueWrite)
                assert confirmation.payload.value == DPTBinary(1)

                with anyio.fail_after(5):
                    val = await sens_recv.receive()
                assert val is True

                # test.sensor=False → GroupValueWrite(0) → BinarySensor.state=False
                await c.set(_KV_SENSOR, value=False)

                with anyio.fail_after(5):
                    confirmation = await st_recv.receive()
                assert isinstance(confirmation.payload, GroupValueWrite)
                assert confirmation.payload.value == DPTBinary(0)

                with anyio.fail_after(5):
                    val = await sens_recv.receive()
                assert val is False

                tg.cancel_scope.cancel()
