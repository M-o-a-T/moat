"""
End-to-end tests for moat.kv.knx.

Each test exercises the full stack:
  knxd (dummy driver + KNXnet/IP tunneling)
  └─ XKNX-device  (simulated KNX actuator / sensor)
  └─ XKNX-monitor (passive bus monitor)

The ``xknx_device`` and ``xknx_monitor`` fixtures are defined in
``conftest.py``.  All tests run under asyncio (xknx is asyncio-only).
"""

from __future__ import annotations

import anyio
import pytest

from xknx.dpt import DPTBinary
from xknx.telegram import GroupAddress, Telegram
from xknx.telegram.apci import GroupValueWrite

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
