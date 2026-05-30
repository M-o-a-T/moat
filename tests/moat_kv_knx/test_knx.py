"""
End-to-end tests for moat.kv.knx.

Each test exercises the full stack:
  knxd (dummy driver + KNXnet/IP tunneling)
  └─ XKNX-device  (simulated KNX actuator / sensor)
  └─ XKNX-monitor (passive bus monitor or controller)

The ``xknx_device`` and ``xknx_monitor`` fixtures are defined in
``conftest.py``.  All tests run under asyncio (xknx is asyncio-only).
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.xknx.devices import Switch
from moat.lib.xknx.dpt import DPTBinary
from moat.lib.xknx.telegram import GroupAddress, Telegram
from moat.lib.xknx.telegram.apci import GroupValueWrite

from moat.kv.knx.mock import SimulatedBinaryDevice

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xknx

pytestmark = pytest.mark.anyio


async def test_monitor(xknx_device: xknx.XKNX, xknx_monitor: xknx.XKNX) -> None:
    """
    Verify that the bus monitor receives a telegram sent by the device instance.

    A :class:`~xknx.telegram.apci.GroupValueWrite` is injected into the
    device instance's outgoing queue.  knxd routes it back to all other
    connected tunnel clients, so the monitor instance should receive it
    as an incoming telegram.
    """
    addr = GroupAddress("1/2/3")
    received: list[Telegram] = []
    evt = anyio.Event()

    def _cb(telegram: Telegram) -> None:
        received.append(telegram)
        evt.set()

    xknx_monitor.telegram_queue.register_telegram_received_cb(_cb)

    xknx_device.telegrams.put_nowait(
        Telegram(
            destination_address=addr,
            payload=GroupValueWrite(value=DPTBinary(1)),
        )
    )

    with anyio.fail_after(5):
        await evt.wait()

    assert len(received) == 1
    tg = received[0]
    assert tg.destination_address == addr
    assert isinstance(tg.payload, GroupValueWrite)
    assert tg.payload.value == DPTBinary(1)


async def test_switch_simulated_binary_device(
    xknx_device: xknx.XKNX,
    xknx_monitor: xknx.XKNX,
) -> None:
    """
    Verify correct interoperation between a Switch and a SimulatedBinaryDevice.

    The test covers two directions:

    **Controller → device**: calling :meth:`~xknx.devices.Switch.set_on` /
    :meth:`~xknx.devices.Switch.set_off` on the Switch sends a
    ``GroupValueWrite`` on the command address.
    :class:`~moat.kv.knx.mock.SimulatedBinaryDevice` receives it, updates
    its internal state, and sends a ``GroupValueWrite`` confirmation on the
    state address.  The Switch receives that confirmation via knxd.

    **Device → controller**: :meth:`~moat.kv.knx.mock.SimulatedBinaryDevice.set_state`
    pushes a ``GroupValueWrite`` on the state address without any preceding
    command.  The Switch receives it and updates its own state.

    The bus monitor (``xknx_monitor``) is also used as the controller
    instance that hosts the Switch; ``xknx_device`` hosts the simulated
    device.  A memory object stream collects each state transition seen by
    the Switch's ``device_updated_cb`` for ordered verification.
    """
    cmd_addr = GroupAddress("0/0/1")
    state_addr = GroupAddress("0/0/2")

    # --- Simulated device on xknx_device ---
    device = SimulatedBinaryDevice(xknx_device, cmd_addr, state_addr)

    # --- Switch controller on xknx_monitor ---
    # sync_state=False prevents the state updater from sending an automatic
    # GroupValueRead at startup, which would pollute the state-telegram stream.
    switch = Switch(
        xknx_monitor,
        "TestSwitch",
        group_address=cmd_addr,
        group_address_state=state_addr,
        sync_state=False,
    )
    xknx_monitor.devices.async_add(switch)

    # Collect every Switch state-update in arrival order.
    # The stream buffer is large enough for the expected updates plus any
    # extras triggered by local outgoing-telegram processing inside xknx.
    sw_send, sw_recv = anyio.create_memory_object_stream[bool | None](max_buffer_size=16)

    def _on_switch(sw: Switch) -> None:
        if sw.state is not None:
            sw_send.send_nowait(sw.state)

    switch.register_device_updated_cb(_on_switch)

    # Collect GroupValueWrite telegrams arriving on the state address at
    # xknx_monitor.  GroupValueResponse telegrams (e.g. from a sync read)
    # are excluded so they don't interfere with the ordered assertions below.
    st_send, st_recv = anyio.create_memory_object_stream[Telegram](max_buffer_size=16)

    def _on_state(tg: Telegram) -> None:
        if isinstance(tg.payload, GroupValueWrite):
            st_send.send_nowait(tg)

    xknx_monitor.telegram_queue.register_telegram_received_cb(
        _on_state, group_addresses=[state_addr]
    )

    # ------------------------------------------------------------------ #
    # Direction 1: Switch set_on → device confirms → state_addr telegram  #
    # ------------------------------------------------------------------ #
    await switch.set_on()

    # Wait for the device's confirmation to arrive at xknx_monitor.
    with anyio.fail_after(5):
        confirmation = await st_recv.receive()

    assert device.state is True
    assert isinstance(confirmation.payload, GroupValueWrite)
    assert confirmation.payload.value == DPTBinary(1)

    # Drain any switch callbacks that fired (local outgoing + bus
    # confirmation).  xknx fires device_updated_cb on local outgoing
    # processing too, so there may be one or two True entries here.
    # The final state seen must be True.
    last: bool | None = None
    with anyio.move_on_after(0.5):
        async for val in sw_recv:
            last = val
    assert last is True

    # ------------------------------------------------------------------ #
    # Direction 1 (repeat): Switch set_off → device confirms              #
    # ------------------------------------------------------------------ #
    await switch.set_off()

    with anyio.fail_after(5):
        confirmation = await st_recv.receive()

    assert device.state is False
    assert isinstance(confirmation.payload, GroupValueWrite)
    assert confirmation.payload.value == DPTBinary(0)

    last = None
    with anyio.move_on_after(0.5):
        async for val in sw_recv:
            last = val
    assert last is False

    # ------------------------------------------------------------------ #
    # Direction 2: device set_state(True) → Switch receives it            #
    # ------------------------------------------------------------------ #
    device.set_state(True)

    # The state telegram arrives at xknx_monitor on the state address.
    with anyio.fail_after(5):
        confirmation = await st_recv.receive()
    assert isinstance(confirmation.payload, GroupValueWrite)
    assert confirmation.payload.value == DPTBinary(1)

    # The Switch must update its state from the incoming state-address telegram.
    with anyio.fail_after(5):
        val = await sw_recv.receive()
    assert val is True
