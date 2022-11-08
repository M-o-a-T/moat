from .device import Register as BaseRegister

import logging
logger = logging.getLogger(__name__)

class Register(BaseRegister):
    def __init__(self, *a, dkv=None, tg=None, **kw):
        super().__init__(*a,**kw)
        if "dest" not in self.data:
            if "slot" in self.data:
                logger.warning(f"{self.unit}:{self.path}: no destination")
            return

        if "slot" not in self.data:
            logger.warning(f"{self.unit}:{self.path}: no slot")
            return
        
        logger.info(f"{self.slot}:{self.path}: Polling")

        if self.data.dest.mark == "r":
            tg.start_soon(self.poll_dkv_raw, dkv)
        else:
            tg.start_soon(self.poll_dkv, dkv)

        if self.data.get("src"):
            if self.data.dest.mark == "r":
                tg.start_soon(self.send_dkv_raw, dkv)
            else:
                tg.start_soon(self.send_dkv, dkv)

    async def poll_dkv(self, dkv):
        async for val in self:
            logger.debug(f"{self.path} R {self.value !r}")
            await dkv.set(self.data.dest, value=self.value, idem=self.data.get("idem", True))

    async def poll_dkv_raw(self, dkv):
        async for val in self:
            logger.debug(f"{self.path} r {self.value !r}")
            await dkv.msg_send(list(self.data.dest), self.value)

    async def send_dkv(self, dkv):
        async for val in dkv.monitor(self.data.dest):
            logger.debug(f"{self.path} W {val.value !r}")
            self.value = val.value

    async def send_dkv_raw(self, dkv):
        async for val in dkv.msg_monitor(self.data.dest):
            logger.debug(f"{self.path} w {val.value !r}")
            self.value = val.value

