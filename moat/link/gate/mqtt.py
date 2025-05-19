"""
MoaT gateway
"""

from __future__ import annotations

import anyio

from moat.link.client import LinkCommon
from . import Gate as _Gate
from moat.util import Path, CFG, NotGiven
from moat.link.meta import MsgMeta

class Gate(_Gate):

    async def get_dst(self, task_status=anyio.TASK_STATUS_IGNORED):
        async with self.link.monitor(self.cf.dst, subtree=True, codec=self.codec) as mon:
            task_status.started()
            ld = len(self.cf.dst)
            while True:
                try:
                    with anyio.fail_after(self.cf.get("timeout",0.5)):
                        msg = await anext(mon)
                except TimeoutError:
                    break
                await self.set_src(Path.build(msg.topic[ld:]), msg.data, msg.meta)
            self.dst_is_current()

            async for msg in mon:
                await self.set_src(Path.build(msg.topic[ld:]), msg.data, msg.meta)


    async def set_dst(self, path:Path, data:Any, meta:MsgMeta):
        if data is NotGiven:
            await self.link.send(self.cf.dst+path, b'', retain=True, codec="noop", meta=MsgMeta(origin=self.origin,timestamp=meta.timestamp))
        else:
            await self.link.send(self.cf.dst+path, data, retain=True, codec=self.codec, meta=MsgMeta(origin=self.origin,timestamp=meta.timestamp))

    def newer_dst(self,node):
        # If the external message has no metadata, it can't be from us,
        # thus assume it's newer.
        if not node.ext_meta:
            return True

        # If the internal and external metadata match, the message is from
        # us, so nothing to do.
        if node.meta == node.ext_meta:
            return None

        # If the internal message has a copy of the outside metadata, it's
        # either unmodified or older. Test the data to be sure.
        if "gw" in node.meta:
            if node.meta["gw"] == node.ext_meta:
                return None if node.data_ == node.ext_data else True
            else:
                return True

        # Otherwise, if the external message is ours, it's old.
        if node.ext_meta.origin == self.origin:
            return False

        # if the timestamps are too close, there might be a problem.
        if abs(node.ext_meta.timestamp-node.meta.timestamp) < .1:
            return None

        # Otherwise use the message with the newer timestamp.
        return node.ext_meta.timestamp > node.meta.timestamp





