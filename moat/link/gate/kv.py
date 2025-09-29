"""
MoaT gateway
"""

from __future__ import annotations

import anyio

from moat.util import NotGiven, Path, PathLongener
from moat.kv.client import Client, open_client
from moat.link.meta import MsgMeta

from . import Gate as _Gate

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.gate import GateNode

    from typing import Any


class Gate(_Gate):  # noqa: D101
    kv: Client

    async def run_(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "Main loop. Overridden to start a Moat-KV client"
        async with open_client("moat.link.gate.kv", **self.cfg["kv"]) as self.kv:
            await super().run_(task_status=task_status)

    async def get_dst(self, task_status=anyio.TASK_STATUS_IGNORED):  # noqa: D102
        pl = PathLongener()
        # This chops the `self.cf.dst` prefix off the resulting path
        async with self.kv.watch(self.cf.dst, fetch=True, long_path=False, nchain=2) as mon:
            task_status.started()
            async for msg in mon:
                if "path" not in msg:
                    if msg.get("state", "") == "uptodate":
                        self.dst_is_current()
                    continue
                path = pl.long(msg.depth, msg.path)
                await self.set_src(
                    path,
                    msg.get("value", NotGiven),
                    MsgMeta(origin=msg.chain.node, t=msg.chain.tick),
                )

    async def set_dst(self, path: Path, data: Any, meta: MsgMeta, node: GateNode):
        "Set KV data."

        meta  # noqa:B018

        # XXX ideally we should have the previous value's external chain
        # available here, just to be able to complain when there's a conflict
        if data is NotGiven:
            res = await self.kv.delete(self.cf.dst + path, nchain=1)
        else:
            res = await self.kv.set(self.cf.dst + path, value=data, nchain=1)

        node.ext_meta = res.chain

    def is_update(self, node: GateNode, data: Any, meta: MsgMeta):
        "Check for update"
        data  # noqa:B018
        # If the message is an echo of what we sent earlier, ignore it.
        try:
            if meta.origin == node.ext_meta.node and meta["t"] == node.ext_meta.tick:
                return False
        except (AttributeError, KeyError):
            pass
        return True

    def newer_dst(self, node):  # noqa: D102
        # If the internal message has a copy of the outside metadata, it
        # should be either unmodified or older. Test the data to be sure.
        # Otherwise compare the chains.
        if node.meta.origin == self.origin:
            return None

        if "gw" in node.meta:
            last_node = node.meta["gw"]
            if last_node.origin != node.ext_meta.origin:
                return True
            if last_node["t"] < node.ext_meta["t"]:
                return True
            if last_node["t"] > node.ext_meta["t"]:
                return False
            return None

        # same data = nothing to do
        # XXX may require inexact comparison for floats
        if node.data == node.ext_data:
            return None

        # Otherwise assume that the local data is newer because there's no
        # gateway data in it.
        return False
