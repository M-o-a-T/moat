"""
Support values on MoaT-KV
"""

import logging

from .device import Register as BaseRegister
from moat.util import Path, NotGiven
import anyio

logger = logging.getLogger(__name__)


class Register(BaseRegister):
    """
    One possibly-complex Modbus register that's mirrored from and/or to MoaT-KV
    """

    def __init__(self, *a, mt_kv=None, tg=None, **kw):
        super().__init__(*a, **kw)
        self.mt_kv = mt_kv

        if self.src is None and self.dest is None:
            if self.data.get("slot", "write") != "write":
                if getattr(self.data, "_is_orig", False):
                    logger.warning("%s:%s: no source/destination", self.unit, self.path)
            return

        logger.info("%s:%s: Polling", self.unit, self.path)

        if (dest := self.dest) is not None:
            slot = self.data.get("slot", None)
            if slot is None:
                logger.warning("%s:%s: no read slot", self.unit, self.path)

            if isinstance(dest, Path):
                dest = (dest,)

            for d in dest:
                if d.mark == "r":
                    tg.start_soon(self.to_dkv_raw, d, mt_kv)
                else:
                    tg.start_soon(self.to_dkv, d, mt_kv)

        if self.src is not None:
            slot = self.data.get("slot", None) if self.dest is None else None
            # if a slot is set AND src is set AND dst is not set,
            # then we want to do a periodic write (keepalive etc.).
            if self.src.mark == "r":
                mon = mt_kv.msg_monitor(self.src)
            else:
                mon = mt_kv.watch(self.src, fetch=True, max_depth=0)

            if slot in (None, "write"):
                tg.start_soon(self.from_dkv, mon)
            else:
                tg.start_soon(self.from_dkv_p, mon, slot)

    @property
    def src(self):
        return self.data.get("src")

    @property
    def dest(self):
        return self.data.get("dest")

    async def to_dkv(self, dest, mt_kv):
        """Copy a Modbus value to MoaT-KV"""
        async for val in self:
#            if "load.goal" in str(dest):
#                breakpoint()
            logger.debug("%s R %r", self.path, val)
            await mt_kv.set(dest, value=val, idem=self.data.get("idem", True))

    async def to_dkv_raw(self, dest, mt_kv):
        """Copy a Modbus value to MQTT"""
        async for val in self:
            logger.debug("%s r %r", self.path, val)
            await mt_kv.msg_send(list(dest), val)

    async def from_dkv(self, mon):
        """Copy a MoaT-KV value to Modbus"""
        async with mon as mon_:
            async for val in mon_:
                if "value" not in val:
                    continue
                logger.debug("%s W %r", self.path, val.value)
                await self._set(val.value)

    async def from_dkv_p(self, mon, slot):
        """Copy an MQTT value to Modbus, with periodic refresh"""
        evt = anyio.Event()
        val = NotGiven
        async def per():
            nonlocal evt, val
            while True:
                if val is NotGiven:
                    await evt.wait()
                else:
                    with anyio.move_on_after(self.cfg.slots[slot]):
                        await evt.wait()
                if val is NotGiven:
                    continue

                await self._set(val)

        async with mon as mon_, anyio.create_task_group() as tg:
            tg.start_soon(per)
            first = True
            async for val_ in mon_:
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
                if d.mark == "r":
                    await self.mt_kv.msg_send(list(d), self.value)
                else:
                    await self.mt_kv.set(d, value=self.value, idem=self.data.get("idem", True))
