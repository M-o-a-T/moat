"""
Per-entry workers for the KNX bus connector.

Each worker drives a single :class:`~moat.link.knx.model.KnxEntry`.
``type=in`` workers watch the KNX bus for incoming telegrams and
publish the decoded value to MoaT-Link; ``type=out`` workers watch a
MoaT-Link value and forward changes onto the bus.
"""

from __future__ import annotations

import anyio
import logging

from moat.util import NotGiven
from moat.lib.xknx.devices import BinarySensor, ExposeSensor, Sensor, Switch

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.lib.xknx import XKNX
    from moat.lib.xknx.telegram import GroupAddress
    from moat.link.client import LinkSender

    from .model import KnxEntry

logger = logging.getLogger(__name__)


def _make_in_device(srv: XKNX, addr: GroupAddress, mode: str, name: str, cb):
    """Build the XKNX device used by a ``type=in`` worker."""
    args: dict = dict(
        xknx=srv,
        group_address_state=addr,
        name=name,
        device_updated_cb=cb,
    )
    if mode == "binary":
        return BinarySensor(ignore_internal_state=True, **args), lambda d: d.is_on()
    dev = Sensor(value_type=mode, **args)
    return dev, lambda d: d.sensor_value.value


def _make_out_device(srv: XKNX, addr: GroupAddress, mode: str, name: str):
    """Build the XKNX device used by a ``type=out`` worker."""
    args: dict = dict(xknx=srv, group_address=addr, name=name)
    if mode == "binary":
        sw = Switch(**args)

        async def set_val(dev, val):
            if val:
                await dev.set_on()
            else:
                await dev.set_off()

        return sw, set_val, lambda d: d.state

    dev = ExposeSensor(value_type=mode, **args)

    async def set_val(dev, val):
        await dev.set(val)

    return dev, set_val, lambda d: d.sensor_value.value


async def run_in(
    link: LinkSender,
    srv: XKNX,
    entry: KnxEntry,
    addr: GroupAddress,
    subpath: Path,
    *,
    initial: bool = False,
) -> None:
    """Forward KNX bus telegrams to a MoaT-Link destination.

    Args:
        link: Active MoaT-Link sender.
        srv: Connected XKNX gateway.
        entry: Configuration entry for this address.
        addr: Group address to listen on.
        subpath: Path of this entry relative to the server (for naming).
        initial: If true, request the current value on startup.
    """
    mode = entry.mode
    dest = entry.dest
    if mode is None or dest is None:
        return

    name = f"{mode}." + ".".join(str(x) for x in subpath)
    evt = anyio.Event()

    def _cb(_dev) -> None:
        evt.set()

    device, get_val = _make_in_device(srv, addr, mode, name, _cb)
    srv.devices.async_add(device)
    try:
        if initial:
            await device.sync()
        while True:
            await evt.wait()
            evt = anyio.Event()
            await link.d_set(dest, get_val(device))
    finally:
        srv.devices.async_remove(device)


async def run_out(
    link: LinkSender,
    srv: XKNX,
    entry: KnxEntry,
    addr: GroupAddress,
    subpath: Path,
    *,
    initial: bool = False,
) -> None:
    """Forward MoaT-Link source updates onto the KNX bus.

    Args:
        link: Active MoaT-Link sender.
        srv: Connected XKNX gateway.
        entry: Configuration entry for this address.
        addr: Group address to write on.
        subpath: Path of this entry relative to the server (for naming).
        initial: If true, fetch the current MoaT-Link value on startup.
    """
    mode = entry.mode
    src = entry.src
    if mode is None or src is None:
        return

    name = f"{mode}." + ".".join(str(x) for x in subpath)
    device, set_val, _get_val = _make_out_device(srv, addr, mode, name)
    srv.devices.async_add(device)
    try:
        async with link.d_watch(src, state=initial or None) as wp:
            async for raw in wp:
                if raw is NotGiven:
                    continue
                await set_val(device, raw)
    finally:
        srv.devices.async_remove(device)
