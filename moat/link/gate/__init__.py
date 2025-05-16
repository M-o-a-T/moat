"""
Gateway to wherever
"""

from __future__ import annotations

import anyio
from attrs import define,field
import logging

from moat.link.node import Node
from moat.link.meta import MsgMeta
from moat.lib.codec import get_codec
from moat.util import NotGiven

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import Watcher
    from moat.lib.codec import Codec

__all__ = ["Gate"]


class GateVanished(RuntimeError):
    "internal error: gate got dropped, or driver changed"
    pass

@define
class GateNode(Node):
    """
    A gatewayed node. It stores the external value and metadata.

    Data and meta 
    """
    ext_meta:dict[str,Any]|None=field(init=False,default=None)
    ext_data:Any=field(init=False,default=NotGiven)

    # todo:bool=field(init=False,default=True)

    @property
    def has_src(self):
        "Check whether source data is present"
        return self.data_ is not NotGiven or self.meta is not in (None,NotGiven)

    @property
    def has_dst(self):
        "Check whether destination data is present"
        return self.ext_data is not NotGiven or self.ext_meta is not in (None,NotGiven)

    @property
    def has_both(self):
        "Check whether both source and destination data are present"
        if self.data_ is NotGiven and self.meta is None:
            return False
        if self.ext_data is NotGiven and self.ext_meta is None:
            return False
        return True


class Gate:
    """
    This is the base class for data gateways.

    Gateways are described by a dict in ``:r.gate.NAME`` with the following
    entries:

    * src: source path, covered by ``moat.link``
    * dst: destination, *must not* be at or under the ``moat.link`` root (if MQTT)
    * driver:
      * mqtt: the destination is a raw MQTT thing
    * codec: Encoding of the destination (source is always ``std-cbor``).
    * retain: ``True/False/None``; the latter is the default and copies
      the data's retain flag

    The gateway works thus:
    * if a data item is not in the source or arrives from dest, copy to source
    * if a data item is not in the destination or arrives from source, copy to dest
    * if the values are equal, do nothing
    * if the source metadata say the data is from the destination, copy dest to source
    * otherwise copy source to dest.

    Subclasses override
    * get_dst
    * set_dst
    * newer_dst
    """

    state:Node
    src:Node
    tg:anyio.abc.TaskGroup
    codec:Codec

    _src_done:anyio.Event
    _dst_done:anyio.Event

    def __init__(self, cfg:dict[str,Any], cf:dict[str,Any], name:str, link:Link):
        """
        Setup.
        @cfg: initial data for this gateway.
        """
        self.cfg = cfg
        self._driver = self.cfg["driver"]
        self.codec = get_codec(self.cfg("codec", "cbor"))

        self.link = link
        self.name = name
        self.origin = "GT:"+name

        self.logger = logging.getLogger(f"moat.link.gate.{name}")

    
    async def get_src(self, *, task_status=anyio.TASK_STATE_IGNORED):
        """
        Fetch the internal data.
        """
        async with self.link.d_watch(self.cfg.conv/self.name, subtree=True,meta=True,mark=True) as mon:
            async for pdm in mon:
                if pdm is None:
                    self._src_done.set()
                    continue
                p,d,m = pdm

                node = self.data.get(path)
                if self.running or node.has_src:
                    await self._set_dst(p,node,d,m)
                else:
                    self.data_ = d
                    self.meta = m

    async def _set_dst(self, path:Path,node:GateNode,data:Any,meta:MsgMeta):
        node.ext_data=NotGiven
        node.ext_meta=NotGiven
        node.data_ = data
        node.meta = meta

        await self.set_dst(path,data,meta)

    def dst_is_current(self):
        self._dst_done.set()

    async def get_dst(self, *, task_status=anyio.TASK_STATE_IGNORED):
        """
        Fetch the external data.

        Override this; call `set_src` with each item.

        You must call `dst_is_current` when the current state has been read
        and you're now waiting for updates. If your backend doesn't support
        this, use a timeout *and* an update counter; `set_src` returns True

        """
        raise NotImplementedError


    async def set_src(self, path:Path, data:Any, aux:dict|None=None):
        """
        Update source state (possibly). @aux is additional metadata that
        the destination resolver can use to disambiguate.
        """
        try:
            data = self.codec.decode(data)
        except Exception as exc:
            self.logger.exception("Remote %s %r/%r: %r", path, data,aux, repr(exc))
            return

        node = self.data.get(path)

        if self.running or node.has_dst:
            await self._set_src(path,node,data,aux)
        else:
            node.ext_data = data
            node.ext_meta = aux or NotGiven

    async def _set_src(self, path:Path,node:GateNode,data:Any,aux:dict|None):
        meta = MsgMeta(origin=self.origin)
        if aux not in {None,NotGiven}:
            meta["gw"] = aux

        await self.link.d_set(path,data,meta)

        node.data_=NotGiven
        node.meta=NotGiven

        node.ext_data = data
        node.ext_meta = aux or NotGiven

    async def set_dst(self, path:Path, data:Any, meta:MsgMeta):
        """
        Update destination state. @meta is the source metadata, in case
        it is useful in some way.
        """
        raise NotImplementedError


    def newer_dst(self, node) -> bool|None:
        """
        Test whether the destination data is newer, based on the node's
        metadata. Return `True` if the data should be copied to the source,
        `False` if the source should be copied to the destination, or
        `None` if inconclusive.

        This method is only called when starting up.
        """
        raise NotImplementedError

    async def run(self, *, task_status=anyio.TASK_STATE_IGNORED):
        """
        Run a bidirectional copy.

        This method auto-restarts the gateway if its data changes.
        It ends if the gateway node is removed or the driver changes.

        The task status is set when the initial sync has completed.

        Called by the system.
        """
        run = True
        while run:
            self.state = Node()
            self.data = GateNode()
            self._src_done=anyio.Event()
            self._dst_done=anyio.Event()
            self.running = False

            try:
                async with anyio.create_task_group() as self.tg:
                    await self.tg.start(self._restart)
                    await self.run_(task_status=task_status)
            except* GateVanished:
                run = False
            else:
                task_status=anyio.TASK_STATE_IGNORED
                await anyio.sleep(1)


    async def _restart(self, *, task_status=anyio.TASK_STATE_IGNORED):
        "Restart the thing when the root changes."
        async with self.link.d_watch(self.cfg.conv/self.name) as mon:
            task_status.started()
            for d in mon:
                if self.cf == d:
                    continue
                breakpoint()
                if d is NotGiven or d.get("driver") != self._driver:
                    raise GateVanished(self.name)
                self.cf = d
                self.tg.cancel_scope.cancel()
                return


    async def run_(self, *, task_status=anyio.TASK_STATE_IGNORED):
        """
        The core runner for the gateway.

        If your implementation needs a context or a support task,
        override this and call the original. `tg` can be used.
        """
        # start initial loops
        await self.tg.start(self.get_src)
        await self.tg.start(self.get_dst)

        # wait for initial scans to be done
        await self._src_done.wait()
        await self._dst_done.wait()
        self.running = True

        # resolve any conflicts in the initial data
        async def visit(path,node):
            if not node.todo:
                return

            if not node.has_src:
                # no source data
                if not node.has_dst:
                    # no destination data
                    return

                # copy dest to source
                d=True

            elif not node.has_dst:
                # copy source to dest
                d=False

            else:
                # both are set. Ugh.
                d = self.newer_dst(node)

            if d is False:
                self.logger.debug("SRC %s %s %r/%r",self.name,path, node.data_,node.meta)
                await self._set_dst(path,node.data_,node.meta)

            elif d is True:
                self.logger.debug("DST %s %s %r/%r",self.name,path, node.data_,node.ext_data,node.ext_meta)

                meta = MsgMeta(origin=self.origin)
                if node.ext_meta:
                    meta["gw"] = node.ext_meta
                await self.link.d_set(path,self.data_,meta)

            elif self.data_ != self.ext_data:
                self.logger.warning("Conflict %s %s %r/%r vs %r/%r",self.name,path, node.data_,node.meta,node.ext_data,node.ext_meta)

        await self.data.walk(visit)
        task_status.started()



    async def state_updater(self, mon:Watcher, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Status update handler.

        By default this just gets the monitor node and updates the raw
        node data in the background.
        """
        node = await mon.get_node()
        task_status.started(node)

        # nothing further to do


def get_gate(cfg: dict, cf: dict) -> Gate:
    """
    Fetch the gate driver named in @cf.
    """
    from importlib import import_module

    name = cfg["driver"]
    if "." not in name:
        name = "moat.link.gate." + name
    return import_module(name).Gate(cfg, cf)
