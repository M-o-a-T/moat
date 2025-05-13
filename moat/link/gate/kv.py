"""
MoaT gateway
"""

from __future__ import annotations

import anyio

from moat.link.client import LinkCommon
from . import Gate as _Gate
from moat.util import Path, CFG
from moat.kv.client import open_client,Client

class Gate(_Gate):

    kv:Client

    async def run(self):
        async with open_client(CFG.kv) as self.kv:
            await super().run()

    async def poll_dst(self, dst:Path, *, task_status=anyio.TASK_STATE_IGNORED):

        async with self.kv.watch(dst, nchain=1, fetch=True) as mon:
            task_status.started()
            async for msg in mon:
                if "value" not in msg:
                    breakpoint()

                await self.src_setter(msg.path, msg.value, msg)

    async def is_update(self, value:Any,meta:MsgMeta, dst_msg)
                if node.





