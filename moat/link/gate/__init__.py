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
from moat.util import NotGiven, P, Path, to_attrdict

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
    ext_meta:dict[str,Any]|None=field(init=False, default=None)
    ext_data:Any=field(init=False, default=NotGiven)
    lock:anyio.abc.Lock=field(init=False, factory=anyio.Lock)

    todo:bool=field(init=False,default=False)

    @property
    def has_src(self):
        "Check whether source data is present"
        return self.data_ is not NotGiven or self.meta not in (None,NotGiven)

    @property
    def has_dst(self):
        "Check whether destination data is present"
        return self.ext_data is not NotGiven or self.ext_meta not in (None,NotGiven)

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

    cfg:attrdict
    cf:attrdict

    def __init__(self, cfg:dict[str,Any], cf:dict[str,Any], path:Path, link:Link):
        """
        Setup.
        @cfg: initial data for this gateway.
        """
        self.cfg = cfg
        self.cf = to_attrdict(cf)
        self.codec = cf.get("codec", "cbor")
        if isinstance(self.codec, str):
            self.codec = get_codec(self.codec)

        self.link = link
        self.path = path
        self.origin = str(Path("GATE")+(P(cf["name"]) if "name" in cf else self.path[1:]))

        self.logger = logging.getLogger(f"moat.link.{path}")

    
    async def get_src(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Fetch the internal data.
        """
        async with self.link.d_watch(self.cf.src, subtree=True,state=None,meta=True,mark=True) as mon:
            task_status.started()
            async for pdm in mon:
                if pdm is None:
                    self._src_done.set()
                    continue
                p,d,m = pdm
                if m is not None and m.origin == self.origin and self._src_done.is_set():
                    # mine, so skip
                    continue

                node = self.data.get(p)
                if self.running or node.has_src:
                    # self.logger.debug("S NOW %r %r %r",p,d,m)
                    await self._set_dst(p,node,d,m)
                else:
                    # self.logger.debug("S DLY %r %r %r",p,d,m)
                    node.set_(p,d,m)
                    node.todo=True

    async def _set_dst(self, path:Path,node:GateNode,data:Any,meta:MsgMeta):
        node.ext_data=NotGiven
        node.ext_meta=NotGiven
        node.set_(path,data,meta)
        node.todo=False

        async with node.lock:
            await self.set_dst(path,data,meta,node)

    def dst_is_current(self):
        self._dst_done.set()

    async def get_dst(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Fetch the external data.

        Override this; call `set_src` with each item.

        You must call `dst_is_current` when the current state has been read
        and you're now waiting for updates. If your backend doesn't support
        this, use a timeout *and* an update counter; `set_src` returns True

        """
        raise NotImplementedError


    async def set_src(self, path:Path, data:Any, aux:MsgMeta):
        """
        Update source state (possibly). @aux is additional metadata that
        the destination resolver can use to disambiguate.
        """
        node = self.data.get(path)

        if self.running or node.has_dst:
            await self._set_src(self.cf.src+path,node,data,aux)
        else:
            node.ext_data = data
            node.ext_meta = aux or NotGiven
            node.todo = True

    async def _set_src(self, path:Path,node:GateNode,data:Any,aux:MsgMeta):
        async with node.lock:
            if not self.is_update(node,data,aux):
                return
            meta = MsgMeta(origin=self.origin)
            if aux not in (None,NotGiven):
                meta["gw"] = aux

            await self.link.d_set(path,data,meta)

            node.set_((),NotGiven,NotGiven)
            node.ext_data = data
            node.ext_meta = aux or NotGiven
            node.todo = False

    async def set_dst(self, path:Path, data:Any, meta:MsgMeta, node:GateNode):
        """
        Update destination state. @meta is the source metadata, in case
        it is useful in some way.
        """
        raise NotImplementedError

    def is_update(self, node:GateNode, data:Any,aux:MsgMeta):
        """
        Check whether this new destination data is an update.
        """
        return True

    def newer_dst(self, node) -> bool|None:
        """
        Test whether the destination data is newer, based on the node's
        metadata. Return `True` if the data should be copied to the source,
        `False` if the source should be copied to the destination, or
        `None` if inconclusive.

        This method is only called when starting up.
        """
        raise NotImplementedError

    async def run(self, *, task_status=anyio.TASK_STATUS_IGNORED):
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
                task_status=anyio.TASK_STATUS_IGNORED
                await anyio.sleep(1)


    async def _restart(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "Restart the thing when the root changes."
        async with self.link.d_watch(self.path) as mon:
            task_status.started()
            async for d in mon:
                if self.cf == d:
                    continue
                if d is NotGiven or d.get("driver") != self.cf.driver:
                    raise GateVanished(str(self.path))
                self.cf = d
                self.tg.cancel_scope.cancel()
                return


    async def run_(self, *, task_status=anyio.TASK_STATUS_IGNORED):
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
                self.logger.debug("SRC %s %s %r/%r",self.path,path, node.data_,node.meta)
                await self._set_dst(path,node,node.data_,node.meta)

            elif d is True:
                self.logger.debug("DST %s %s %r/%r",self.path,path, node.ext_data,node.ext_meta)

                meta = MsgMeta(origin=self.origin)
                if node.ext_meta:
                    meta["gw"] = node.ext_meta
                await self.link.d_set(self.cf.src+path,node.ext_data,meta)

            elif node.data_ != node.ext_data:
                self.logger.warning("Conflict %s %s %r/%r vs %r/%r",self.path,path, node.data_,node.meta,node.ext_data,node.ext_meta)

        await self.data.walk(visit, force=True)
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


async def run_gate(cfg: dict, link:Link, cf:Path|str, *, task_status=anyio.TASK_STATUS_IGNORED):
    """
    Run a gate in @link, described by @name.
    """
    from importlib import import_module

    if isinstance(cf,str):
        cf = P("gate")/cf
    path = cf
    cf = await link.d_get(path)

    drv = cf["driver"]
    if "." not in drv:
        drv = "moat.link.gate." + drv
    gate = import_module(drv).Gate(cfg, cf, path, link)
    await gate.run(task_status=task_status)
