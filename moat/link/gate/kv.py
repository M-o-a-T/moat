"""
MoaT gateway
"""

from __future__ import annotations

import anyio

from moat.link.client import LinkCommon
from . import Gate as _Gate
from moat.util import Path, CFG, NotGiven, PathLongener
from moat.link.meta import MsgMeta
from moat.kv.client import Client,open_client

class Gate(_Gate):
    kv:Client

    async def run_(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "Main loop. Overridden to start a Moat-KV client"
        async with open_client("moat.link.gate.kv", **self.cfg) as self.kv:
            await super().run_(task_status=task_status)

    async def get_dst(self, task_status=anyio.TASK_STATUS_IGNORED):
        pl=PathLongener()
        # This chops the `self.cf.dst` prefix off the resulting path
        async with self.kv.watch(self.cf.dst, fetch=True, long_path=False, nchain=2) as mon:
            task_status.started()
            async for msg in mon:
                if "value" not in msg:
                    if msg.get("state","")=="uptodate":
                        self.dst_is_current()
                    continue
                path=pl.long(msg.depth,msg.path)
                await self.set_src(path, msg.value, MsgMeta(origin=msg.chain.node,t=msg.chain.tick))


    async def set_dst(self, path:Path, data:Any, meta:MsgMeta):
        "Set KV data."
        # XXX ideally we should have the previous value's external chain
        # available here, just to be able to complain when there's a conflict
        if data is NotGiven:
            await self.kv.delete(self.cf.dst+path)
        else:
            await self.kv.set(self.cf.dst+path, value=data)


    def newer_dst(self,node):
        # If the internal message has a copy of the outside metadata, it
        # should be either unmodified or older. Test the data to be sure.
        # Otherwise compare the chains.
        if "kv" in node.meta:
            chain = NodeEvent.deserialize_link(node.meta["kv"])
            if chain == node.ext_meta:
                if node.data_ == node.ext_data:
                    return None
                self.logger.warn("Data mismatch: %r %r/%r %r/%r", node.path, node.data_,node.meta, nod.ext_data,node.ext_meta)
                return True
            elif chain > node.ext_meta:
                return False
            elif chain < node.ext_meta:
                return True
            else:
                return None

        # Otherwise just assume that our data is newer.
        return False

