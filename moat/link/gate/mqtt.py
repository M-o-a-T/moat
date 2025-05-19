"""
MoaT gateway
"""

from __future__ import annotations

import anyio

from moat.link.client import LinkCommon
from . import Gate as _Gate
from moat.util import Path, CFG

class Gate(_Gate):

    async def get_dst(self, task_status=anyio.TASK_STATUS_IGNORED):
        async with self.link.monitor(self.cfg.dst, subtree=True) as mon:
            task_status.started()
            while True:
                with anyio.move_on_after(self.cfg.get("timeout",0.5)):
                    msg = await anext(mon)



        async with self.kv.watch(dst, nchain=1, fetch=True) as mon:
            task_status.started()
            async for msg in mon:
                if "value" not in msg:
                    breakpoint()

                await self.src_setter(msg.path, msg.value, msg)

    async def set_dst(self, path:Path, data:Any, meta:MsgMeta):
        if data is NotGiven:
            await self.link.send(self.cf.dst+path, b'', retain=True, codec="noop", meta=MsgMeta(origin=self.origin,timestamp=meta.timestamp))
        else:
            await self.link.send(self.cf.dst+path, data, retain=True, codec=self.codec, meta=MsgMeta(origin=self.origin,timestamp=meta.timestamp))

    def newer_dst(self,node):
        if not node.ext_meta:
            return True
        if node.ext_meta.origin == self.origin:
            return False
        if abs(node.ext_meta.timestamp-node.meta.timestamp) < .1:
            return None
        return node.ext_meta.timestamp > node.meta.timestamp





