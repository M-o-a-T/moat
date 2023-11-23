"""
Support values on MoaT-KV
"""

import logging

from .device import Register as BaseRegister

logger = logging.getLogger(__name__)


class Register(BaseRegister):
    """
    One possibly-complex Modbus register that's mirrored from and/or to MoaT-KV
    """

    def __init__(self, *a, mt_kv=None, tg=None, **kw):
        super().__init__(*a, **kw)
        self.mt_kv = mt_kv

        if "dest" not in self.data and "src" not in self.data:
            if self.data.get("slot", "write") != "write":
                logger.warning("%s:%s: no source/destination", self.unit, self.path)
            return

        logger.info("%s:%s: Polling", self.unit, self.path)

        if self.data.get("dest"):
            if self.data.get("slot", "write") == "write":
                logger.warning("%s:%s: no read slot", self.unit, self.path)

            elif self.data.dest.mark == "r":
                tg.start_soon(self.poll_dkv_raw, mt_kv)
            else:
                tg.start_soon(self.poll_dkv, mt_kv)

        if self.data.get("src"):
            if self.data.src.mark == "r":
                tg.start_soon(self.send_dkv_raw, mt_kv)
            else:
                tg.start_soon(self.send_dkv, mt_kv)

    async def poll_dkv(self, mt_kv):
        """Copy a Modbus value to MoaT-KV"""
        async for val in self:
            logger.debug("%s R %r", self.path, val)
            await mt_kv.set(self.data.dest, value=val, idem=self.data.get("idem", True))

    async def poll_dkv_raw(self, mt_kv):
        """Copy a Modbus value to MQTT"""
        async for val in self:
            logger.debug("%s r %r", self.path, val)
            await mt_kv.msg_send(list(self.data.dest), val)

    async def send_dkv(self, mt_kv):
        """Copy a MoaT-KV value to Modbus"""
        async with mt_kv.watch(self.data.src) as mon:
            async for val in mon:
                logger.debug("%s W %r", self.path, val.value)
                await self._set(val.value)

    async def send_dkv_raw(self, mt_kv):
        """Copy an MQTT value to Modbus"""
        async with mt_kv.msg_monitor(self.data.src) as mon:
            async for val in mon:
                logger.debug("%s w %r", self.path, val.value)
                await self._set(val.value)

    async def _set(self, value):
        self.value = value

        if self.data.get("dest") and self.data.get("mirror", False):
            if self.data.dest.mark == "r":
                await self.mt_kv.msg_send(list(self.data.dest), self.value)
            else:
                await self.mt_kv.set(
                    self.data.dest, value=self.value, idem=self.data.get("idem", True)
                )
