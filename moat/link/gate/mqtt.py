"""
MoaT gateway
"""

from __future__ import annotations

import anyio

from moat.link.client import LinkCommon
from . import Gate as _Gate
from moat.util import Path, CFG

class Gate(_Gate):

    async def get_dst(self, task_status=anyio.TASK_STATE_IGNORED):
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

    async def is_update(self, value:Any,meta:MsgMeta, dst_msg)
                if node.





