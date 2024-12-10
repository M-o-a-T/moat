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

    def __init__(self, *a, mt_kv=None, tg=None, is_server=False, **kw):
        super().__init__(*a, **kw)
        self.mt_kv = mt_kv
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
                if d.mark == "r":
                    tg.start_soon(self.to_dkv_raw, d)
                else:
                    tg.start_soon(self.to_dkv, d)

        if self.src is not None:
            slot = self.data.get("slot", None) if self.dest is None else None
            # if a slot is set AND src is set AND dst is not set,
            # then we want to do a periodic write (keepalive etc.).
            if self.src.mark == "r":
                mon = self.mt_kv.msg_monitor(self.src)
            else:
                mon = self.mt_kv.watch(self.src, fetch=True, max_depth=0)

            # logger.info("%s:%s: Watch %s", self.unit, self.path,self.src)

            if self.is_server or slot in (None, "write"):
                await tg.start(self.from_dkv, mon)
            else:
                tg.start_soon(self.from_dkv_p, mon, self.slot.write_delay)

    @property
    def src(self):
        return self.data.get("src")

    @property
    def dest(self):
        return self.data.get("dest")

    def set(self, val):
        self.reg.set(val)

    async def to_dkv(self, dest):
        """Copy a Modbus value to MoaT-KV"""
        async for val in self:
#            if "load.goal" in str(dest):
#                breakpoint()
            logger.debug("%s R %r", self.path, val)
            await self.mt_kv.set(dest, value=val, idem=self.data.get("idem", True))

    async def to_dkv_raw(self, dest):
        """Copy a Modbus value to MQTT"""
        async for val in self:
            logger.debug("%s r %r", self.path, val)
            await self.mt_kv.msg_send(list(dest), val)

    async def from_dkv(self, mon, *, task_status):
        """Copy a MoaT-KV value to Modbus"""
        async with mon as mon_:
            async for val in mon_:
                if task_status is not None:
                    task_status.started()
                    task_status = None
                if "value" not in val:
                    logger.debug("%s Wx", self.path)
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
