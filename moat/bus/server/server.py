"""
This module implements the basics for a bus server.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from functools import partial
from weakref import ref

import msgpack
import trio

from moat.bus.message import BusMessage
from moat.bus.util import CtxObj, Dispatcher

from .obj import Obj

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.bus.backend import BaseBusHandler

logger = logging.getLogger(__name__)

packer = msgpack.Packer(
    strict_types=False,
    use_bin_type=True,  # default=_encode
).pack
unpacker = partial(msgpack.unpackb, raw=False)

# Errors


class NoFreeID(RuntimeError):  # noqa:D101
    pass


class IDcollisionError(RuntimeError):  # noqa:D101
    pass


# Events


class ServerEvent:  # noqa:D101
    pass


class _ClientEvent(ServerEvent):
    def __init__(self, obj):
        self.obj = obj

    def __repr__(self):
        return "<{} {}>".format(self.__class__.__name__.replace("Event", ""), self.obj)


class NewClientEvent(_ClientEvent):
    """
    A device has obtained a client address. Get data dictionary and stuff.
    """

    pass


class OldClientEvent(_ClientEvent):
    """
    An existing device has re-fetched its address; we might presume that
    it's been rebooted.
    """

    pass


class DropClientEvent(_ClientEvent):
    """
    A device has been removed.
    """

    pass


class ClientStore:  # noqa:D101
    def __init__(self, server):
        self._server = ref(server)
        self._id2obj = dict()
        self._ser2obj = dict()
        self._next_id = 1  # last valid ID
        self._reporter = set()
        super().__init__()

    @property
    def server(self):  # noqa:D102
        return self._server()

    def obj_serial(self, serial, create=None):
        """
        Get object by serial#.
        """
        try:
            obj = self._ser2obj[serial]
        except KeyError:
            if create is False:
                raise
            obj = Obj(serial)
        else:
            if create is True:
                raise KeyError
        return obj

    def obj_client(self, client: int):
        """
        Get object by current client ID
        """
        return self._id2obj[client]

    @property
    def free_client_id(self):
        """
        Property: Returns a free client ID.
        """
        nid = self._next_id
        while True:
            cid = nid
            # skip 127 and 0
            if nid > 126:
                nid = 0
            nid += 1
            if cid not in self._id2obj:
                self._next_id = nid
                return cid
            if nid == self._next_id:
                raise NoFreeID(self)

    async def register(self, obj):
        """
        Register a bus object.
        """
        await self.deregister(obj)

        # Happens when we restart / observe another server's assignment
        try:
            new_id = obj.client_id
            if new_id is None:
                obj.client_id = self.free_client_id

            self._ser2obj[obj.serial] = obj
            self._id2obj[obj.client_id] = obj
            if new_id is None:
                await obj.attach(self.server)
                await self.report(NewClientEvent(obj))
            else:
                await self.report(OldClientEvent(obj))
        except BaseException:
            with trio.move_on_after(1) as sc:
                sc.shield = True
                await self.deregister(obj)
            raise

    async def deregister(self, obj):
        """
        De-register a bus object.
        """
        if obj.serial in self._ser2obj:
            await self.report(DropClientEvent(obj))
        await obj.detach(self.server)
        try:
            # Order is important.
            del self._ser2obj[obj.serial]
            del self._id2obj[obj.client_id]
            del obj.client_id
        except (AttributeError, KeyError):
            pass

    @contextmanager
    def watch(self):  # noqa:D102
        q_w, q_r = trio.open_memory_channel(10)
        self._reporter.add(q_w.send)
        try:
            yield q_r
        finally:
            self._reporter.remove(q_w.send)

    async def report(self, evt):  # noqa:D102
        for q in self._reporter:
            await q(evt)


class Server(CtxObj, Dispatcher):
    """
    Bus server.

    Basic usage::

        async with Server(backend, id) as server:
            async for evt in server:
                await handle_event(evt)
                await server.send_msg(some_message)
    """

    _check_task = None

    def __init__(self, backend: BaseBusHandler, id=1):
        if id < 1 or id > 3:
            raise RuntimeError("My ID must be within 1…3")
        self.logger = logging.getLogger(f"{__name__}.{backend.id}")
        self._back = backend
        self.__id = id - 4  # my server ID
        self.objs = ClientStore(self)

        super().__init__()

    @property
    def my_id(self):  # noqa:D102
        return self.__id

    async def sync_in(self, client):
        """
        Check if a sync message has arrived on the bus; if so, wait until
        the change described in it has arrived on the client
        """
        client  # noqa:B018
        pass  # TODO

    async def sync_out(self, client, chain):
        """
        Send a "this chain must have arrived at your node to proceed"
        message to the bus
        """
        client  # noqa:B018
        msg = [chain.node.name, chain.tick]
        # XXX shorten this? the node should correspond to the other server's ID

        await self.send(src=self.id, dst=-4, code=0, data=packer(msg))

    @asynccontextmanager
    async def _ctx(self):
        async with trio.open_nursery() as n:
            await n.start(self._reader)
            try:
                self.__n = n
                yield self
            finally:
                del self.__n
                n.cancel_scope.cancel()

    async def _reader(self, *, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        async for msg in self._back:
            await self.dispatch(msg)

    def get_code(self, msg):
        """Code zero"""
        return msg.code

    async def send(self, src, dst, code, data=b"", prio=0):  # noqa:D102
        msg = BusMessage()
        msg.start_send()
        msg.src = src
        msg.dst = dst
        msg.code = code
        msg.prio = prio
        msg.add_data(data)
        await self.send_msg(msg)

    async def send_msg(self, msg):  # noqa:D102
        await self._back.send(msg)

    async def reply(self, msg, src=None, dest=None, code=None, data=b"", prio=0):  # noqa:D102
        if src is None:
            src = msg.dst
        if dest is None:
            dest = msg.src
        if code is None:
            code = 3  # standard reply
        await self.send(src, dest, code, data=data, prio=prio)
