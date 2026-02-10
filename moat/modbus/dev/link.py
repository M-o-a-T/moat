"""
Support values on MoaT-KV
"""

from __future__ import annotations

import anyio
import logging

from moat.util import NotGiven
from moat.lib.path import Path

from .device import Register as BaseRegister

logger = logging.getLogger(__name__)


class Register(BaseRegister):
    """
    One possibly-complex Modbus register that's mirrored from and/or to MoaT-Link
    """

    def __init__(self, *a, link=None, tg=None, is_server=False, **kw):
        super().__init__(*a, **kw)
        self._link = link
        self.tg = tg
        self.is_server = is_server
        self.mqtt_event = anyio.Event()
        self.last_sent_value = None

        if self.src is None and self.dest is None:
            if self.data.get("slot", "write") != "write":
                if getattr(self.data, "_is_orig", False):
                    logger.warning("%s:%s: no source/destination", self.unit, self.path)
            return

    async def start(self):  # noqa: D102
        await super().start()

        # logger.info("%s:%s: Polling", self.unit, self.path)
        tg = self.tg

        if (dest := self.dest) is not None:
            if self.is_server:
                slot = None
                # Server-side registers wait on DataBlock.changed event
                tg.start_soon(self._watch_datablock_changes)
            else:
                slot = self.data.get("slot", None)
                if slot is None:
                    logger.warning("%s:%s: no read slot", self.unit, self.path)
                else:
                    # Register this Link Register for MQTT notification
                    # self.slot should have been set in BaseRegister.__init__
                    try:
                        self.slot.mqtt_registers.add(self)
                    except AttributeError:
                        logger.error(
                            "%s: slot attribute not set despite slot='%s' in data",
                            self.path,
                            slot,
                        )

            # logger.info("%s:%s: Write %s", self.unit, self.path, dest)
            if isinstance(dest, Path):
                dest = (dest,)

            for d in dest:
                tg.start_soon(self.to_link, d)

        # Handle const: !P path - subscribe to MQTT and update READ value
        # (not write value - we don't want to trigger writes back to the device)
        if "const" in self.data:
            const_val = self.data.const
            if isinstance(const_val, Path):
                mon = self._link.d_watch(const_val, meta=True)
                await tg.start(self.from_link_const, mon)

        if self.src is not None:
            slot = self.data.get("slot", None) if self.dest is None else None
            # if a slot is set AND src is set AND dst is not set,
            # then we want to do a periodic write (keepalive etc.).
            mon = self._link.d_watch(self.src, meta=True)

            # logger.info("%s:%s: Watch %s", self.unit, self.path,self.src)

            if self.is_server or slot in (None, "write"):
                await tg.start(self.from_link, mon)
            else:
                tg.start_soon(self.from_link_p, mon, self.slot.write_delay)

    @property
    def src(self):  # noqa: D102
        return self.data.get("src")

    @property
    def dest(self):  # noqa: D102
        return self.data.get("dest")

    def set(self, val):  # noqa: D102
        self.reg.set(val)

    async def _watch_datablock_changes(self):
        """Wait on DataBlock.changed event and notify if this register changed."""
        # Wait for register to be added to a DataBlock
        while True:
            await self.block.changed.wait()
            # DataBlock.changed fires for ANY register change
            # Check if this specific register changed
            if self.reg._changed:  # noqa: SLF001  # Flag set by BaseValue.decode
                self.reg._changed = False  # noqa: SLF001
                self.mqtt_event.set()

    async def to_link(self, dest):
        """Copy a Modbus value to MoaT-Link when notified by slot."""
        # Read current MQTT value on startup
        try:
            self.last_sent_value = await self._link.d_get(dest)
        except KeyError:
            self.last_sent_value = None

        while True:
            # Wait for slot notification
            await self.mqtt_event.wait()
            self.mqtt_event = anyio.Event()  # Recreate for next notification

            # Get transformed value and send if changed
            val = self.value
            if val != self.last_sent_value:
                logger.info("%s L %r -> MQTT", self.path, val)
                await self._link.d_set(dest, val, retain="idle" not in self.data)
                self.last_sent_value = val

    async def from_link(self, mon, *, task_status):
        """Copy an MQTT value to Modbus (sets write value, triggers bus update)"""
        async with mon as mon_:
            if task_status is not None:
                task_status.started()
                task_status = None
            async for val in mon_:
                if val is None:  # Link message
                    continue
                if isinstance(val, tuple):  # Link client
                    val = val[0]  # noqa:PLW2901
                elif "value" not in val:  # KV message
                    logger.debug("%s Wx", self.path)
                    continue
                else:
                    val = val.value  # noqa:PLW2901
                if (idle := self.data.get("idle")) is not None and val == idle:
                    continue
                logger.debug("%s W %r", self.path, val)
                await self._set(val)

    async def from_link_const(self, mon, *, task_status):
        """Copy an MQTT value to Modbus for const: !P (sets read value only, no bus update)"""
        async with mon as mon_:
            if task_status is not None:
                task_status.started()
                task_status = None
            async for val in mon_:
                if val is None:  # Link message
                    continue
                if isinstance(val, tuple):  # Link client
                    val = val[0]  # noqa:PLW2901
                elif "value" not in val:  # KV message
                    logger.debug("%s Cx", self.path)
                    continue
                else:
                    val = val.value  # noqa:PLW2901
                logger.debug("%s C %r", self.path, val)
                # Update the READ value, not the write value
                # This makes the value available when read via Modbus server
                # but doesn't trigger a write back to the remote device
                self.reg._value = val  # noqa: SLF001

    async def from_link_p(self, mon, slot):
        """Copy an MQTT value to Modbus, with periodic refresh"""
        evt = anyio.Event()
        val = NotGiven

        async def per():
            nonlocal evt, val
            while True:
                if val is NotGiven:
                    await evt.wait()
                else:
                    with anyio.move_on_after(slot):
                        await evt.wait()
                if val is NotGiven:
                    continue
                logger.debug("%s Wr %r", self.path, val)
                await self._set(val)

        async with mon as mon_, anyio.create_task_group() as tg:
            tg.start_soon(per)
            first = True
            async for val_ in mon_:
                if isinstance(val, tuple):
                    val = val[0]
                else:
                    try:
                        val = val_.value
                    except AttributeError:
                        if first:
                            first = False
                            continue
                        val = NotGiven
                if val is not NotGiven:
                    if (idle := self.data.get("idle")) is not None and val == idle:
                        continue
                    logger.debug("%s w %r", self.path, val)
                evt.set()
                evt = anyio.Event()

    async def _set(self, value):
        self.value = value

        if (dest := self.dest) is not None and self.data.get("mirror", False):
            if isinstance(dest, Path):
                dest = (dest,)

            for d in dest:
                await self._link.d_set(d, value, retain=True)
