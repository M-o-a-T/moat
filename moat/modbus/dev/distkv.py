"""
Support values on DistKV
"""

import logging

from .device import Register as BaseRegister

logger = logging.getLogger(__name__)


class Register(BaseRegister):
    """
    One possibly-complex Modbus register that's mirrored from and/or to DistKV
    """

    def __init__(self, *a, dkv=None, tg=None, **kw):
        super().__init__(*a, **kw)
        self.dkv = dkv

        if "dest" not in self.data and "src" not in self.data:
            if self.data.get("slot", "write") != "write":
                logger.warning("%s:%s: no source/destination", self.unit, self.path)
            return

        logger.info("%s:%s: Polling", self.unit, self.path)

        if self.data.get("dest"):
            if self.data.get("slot", "write") == "write":
                logger.warning("%s:%s: no read slot", self.unit, self.path)

            elif self.data.dest.mark == "r":
                tg.start_soon(self.poll_dkv_raw, dkv)
            else:
                tg.start_soon(self.poll_dkv, dkv)

        if self.data.get("src"):
            if self.data.src.mark == "r":
                tg.start_soon(self.send_dkv_raw, dkv)
            else:
                tg.start_soon(self.send_dkv, dkv)

    async def poll_dkv(self, dkv):
        """Copy a Modbus value to DistKV"""
        async for val in self:
            logger.debug("%s R %r", self.path, val)
            await dkv.set(self.data.dest, value=val, idem=self.data.get("idem", True))

    async def poll_dkv_raw(self, dkv):
        """Copy a Modbus value to MQTT"""
        async for val in self:
            logger.debug("%s r %r", self.path, val)
            await dkv.msg_send(list(self.data.dest), val)

    async def send_dkv(self, dkv):
        """Copy a DistKV value to Modbus"""
        async with dkv.watch(self.data.src) as mon:
            async for val in mon:
                logger.debug("%s W %r", self.path, val.value)
                await self._set(val.value)

    async def send_dkv_raw(self, dkv):
        """Copy an MQTT value to Modbus"""
        async with dkv.msg_monitor(self.data.src) as mon:
            async for val in mon:
                logger.debug("%s w %r", self.path, val.value)
                await self._set(val.value)

    async def _set(self, value):
        self.value = value

        if self.data.get("dest") and self.data.get("mirror", False):
            if self.data.dest.mark == "r":
                await self.dkv.msg_send(list(self.data.dest), self.value)
            else:
                await self.dkv.set(
                    self.data.dest, value=self.value, idem=self.data.get("idem", True)
                )
