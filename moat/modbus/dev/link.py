"""
Support values on MoaT-KV
"""

from __future__ import annotations

import logging

from .device import Register as BaseRegister
from moat.util import Path, NotGiven
import anyio

logger = logging.getLogger(__name__)


class Register(BaseRegister):
    """
    One possibly-complex Modbus register that's mirrored from and/or to MoaT-KV
    """

    def __init__(self, *a, link=None, tg=None, is_server=False, **kw):
        super().__init__(*a, **kw)
        self._link = link
        self.tg = tg
        self.is_server = is_server

        if self.src is None and self.dest is None:
            if self.data.get("slot", "write") != "write":
                if getattr(self.data, "_is_orig", False):
                    logger.warning("%s:%s: no source/destination", self.unit, self.path)
            return

    async def start(self):
        await super().start()

        # logger.info("%s:%s: Polling", self.unit, self.path)
        tg = self.tg

        if (dest := self.dest) is not None:
            if self.is_server:
                slot = None
            else:
                slot = self.data.get("slot", None)
                if slot is None:
                    logger.warning("%s:%s: no read slot", self.unit, self.path)

            # logger.info("%s:%s: Write %s", self.unit, self.path, dest)
            if isinstance(dest, Path):
                dest = (dest,)

            for d in dest:
                tg.start_soon(self.to_link, d)

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
    def src(self):
        return self.data.get("src")

    @property
    def dest(self):
        return self.data.get("dest")

    def set(self, val):
        self.reg.set(val)

    async def to_link(self, dest):
        """Copy a Modbus value to MoaT-Link"""
        async for val in self:
            logger.debug("%s L %r", self.path, val)
            await self._link.d_set(dest, val, retain=True)

    async def from_link(self, mon, *, task_status):
        """Copy an MQTT value to Modbus"""
        async with mon as mon_:
            if task_status is not None:
                task_status.started()
                task_status = None
            async for val in mon_:
                if val is None:  # Link message
                    continue
                if isinstance(val,tuple):  # Link client
                    logger.debug("%s W %r", self.path, val)
                    val=val[0]
                elif "value" not in val:  # KV message
                    logger.debug("%s Wx", self.path)
                    continue
                else:
                    logger.debug("%s W %r", self.path, val)
                    val=val.value
                await self._set(val)

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
                if isinstance(val,tuple):
                    val = val[0]
                else:
                    try:
                        val = val_.value
                    except AttributeError:
                        if first:
                            first = False
                            continue
                        val = NotGiven
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
