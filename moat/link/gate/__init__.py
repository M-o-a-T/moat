"""
Gateway to wherever
"""

from __future__ import annotations

import anyio
from attrs import define,field

from moat.link.node import Node
from moat.link.meta import MsgMeta
from moat.util import NotGiven

from typing import TYPE_CHECKING,overload
if TYPE_CHECKING:
    from .client import Watcher


@define
class GateNode(Node):
    """
    A gatewayed node. It stores the external value and metadata.
    """
    ext_meta=field(init=False,default=None)
    ext_value:Any=field(init=False,default=NotGiven)

    todo:bool=field(init=False,default=True)


class Gate:
    """
    This is the base class for data gateways.

    Gatewaying works liek this:
    * the local and remote data are collected into the GateNode tree.

    """
    state:Node
    src:Node
    tg:anyio.abc.TaskGroup

    _src_done:anyio.Event
    _dst_done:anyio.Event

    def __init__(self, cfg:dict[str,Any], name:str, link:Link):
		self.cfg = cfg
		self.link = link
        self.name = name
        self.origin = "GT:"+name

        self._src_done=anyio.Event()
        self._dst_done=anyio.Event()

    @property
    def cf(self):
        return self.state.data

    async def copy_src(self, *, task_status=anyio.TASK_STATE_IGNORED):
        """
        Fetch the internal data.
        """
        async with self.link.d_watch(self.cfg.conv/self.name, subtree=True) as mon:
            async for pdm in mon:
                if pdm is None:
                    self._src_done.set()
                    continue



    async def copy_dst(self, *, task_status=anyio.TASK_STATE_IGNORED):
        """
        Fetch the external data.
        """
		raise NotImplementedError

    async def run(self, name):
        """
        Fetch the gateway state and then call `run`.
        """
        async with (
            self.link.d_watch(self.cfg.conv/self.name, subtree=True) as mon,
            anyio.create_task_group() as self.tg,
        ):
            self.state = await tg.start(self.state_updater,mon)
            self.src = await tg.start(self.state_updater,mon)
            


    async def state_updater(self, mon:Watcher, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Status update handler.

        By default this just gets the monitor node and updates the raw
        node data in the background.
        """
        node = await mon.get_node()
        task_status.started(node)

        # nothing further to do

    async def poll_dst(self, dst:Path, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Destination update handler.

        Task: Iterate data at the destination and call `src_setter` with
        each item that might be new.

        Must be overridden.
        """
		raise NotImplementedError


    async def src_setter(self, path:Path, data:Any, dst_msg:Any) -> None:
        """
        Source data updater. Called from `poll_dst`.
        """
        if data is NotGiven:  # delete
            try:
                node = self.node.get(path, create=False)
            except KeyError:
                return
            if node.data_ is NotGiven:
                return
        else:
            node = self.node.get(path)

        if self.is_update(node,data,dst_msg):
            self.logger.debug("UpdSrc",dst,data)
            await self.link.d_set(dst,data,meta=MsgMeta(origin=self.origin,timestamp=t))

		raise NotImplementedError


    async def is_update(self, node:Node, value:Any, dst_msg:Any) -> bool:
        """
        Check whether the remote message should update this node.
        """
		raise NotImplementedError


    async def dst_changed(self, dst:Path, data:Any, **kw) -> None:
        """
        Destination data updater.

        Must be overridden.
        """
		raise NotImplementedError


def get_gate(cfg: dict, **kw) -> Gate:
    """
    Fetch the gate named in the config and initialize it.
    """
    from importlib import import_module

    name = cfg["driver"]
    if "." not in name:
        name = "moat.link.gate." + name
    return import_module(name).Gate(cfg, **kw)
