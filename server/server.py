"""
This module implements the basics for a bus server.
"""

import trio
from contextlib import asynccontextmanager

from .backend import BaseBusHandler
from .message import BusMessage

# Errors

class NoFreeID(RuntimeError):
    pass
class IDcollisionError(RuntimeError):
    pass

# Events

class ServerEvent:
    pass

class NewDeviceEvent(ServerEvent):
    """
    A device has obtained a client address. Get data dictionary and stuff.
    """
    def __init__(self, obj):
        self.obj = obj

class OldDeviceEvent(ServerEvent):
    """
    An existing device has re-fetched its address; we might presume that
    it's been rebooted.
    """
    def __init__(self, obj):
        self.obj = obj

class BroadcastMsg(ServerEvent):
    def __init__(self, msg):
        self.msg = msg

class DirectMsg(ServerEvent):
    def __init__(self, msg):
        self.msg = msg


class CommandHandler:
    pass

class Server:
    """
    Bus server.

    Basic usage::

        async with Server(backend, id) as server:
            async for evt in server:
                await server.handle_event(evt)
    """
    _check_task = None

    def __init__(self, backend:BaseBusHandler, id=1):
        self.log = logging.getLogger("%s.%s" % (__name__, backend.name))
        self._back = backend
        self.id2obj = dict()
        self.ser2obj = dict()
        self.id = id-4  # my server ID
        self.q_w, self.q_r = trio.open_memory_channel(100)
        self._next_id = 1 # last valid ID

    def get_free_id(self):
        """
        Returns a free client ID.
        """
        nid = self._next_id
        while True:
            cid = nid
            if nid > 126:
                nid = 0
            nid += 1
            if cid not in self.id2obj:
                self._next_id = nid
                return cid
            if nid == self._next_id:
                raise NoFreeID(self)

    def with_serial(self, serial, bus_id=None):
        try:
            obj = self.ser2obj[serial]
        except KeyError:
            obj = Obj(serial)
            if bus_id is not None:
                obj.__reg_id = bus_id
            obj.attach(self)
        else:
            self.logger.warn("Server sync problem? %r: %d vs. %d", obj, obj.__reg_id, bus_id)
            if obj.__reg_id > bus_id:
                obj.detach()
                obj.__reg_id = bus_id
                obj.attach(self)
        return obj

    def register(self, obj):
        """
        Register a bus object. Multiple calls are OK.
        """
        self.deregister(obj)
        try:
            # Happens when we observe another server's assignment
            new_id = obj.__reg_id
        except AttributeError:
            new_id = self.get_free_id()

        self.ser2obj[obj.serial] = obj
        self.id2obj[new_id] = obj
        obj.__reg_id = new_id
        obj.__data = None

    def bus_id(self, obj):
        return obj.__reg_id

    def deregister(self, obj):
        """
        De-register a bus object. Multiple calls are OK.
        """
        try:
            # Order is important.
            del self.ser2obj[obj.serial]
            del self.id2obj[obj.__reg_id]
            del obj.__reg_id
        except (AttributeError,KeyError):
            pass

    def __aenter__(self):
        self.__ctx = ctx = self._ctx()
        return ctx.__aenter__()

    def __aexit__(self, *tb):
        ctx = self.__ctx
        del self.__ctx
        return ctx.__aexit__(*tb)

    def __aiter__(self):
        return self

    def __anext__(self):
        return self.q_r.__anext__()

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

    async def _reader(self, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        async for msg in self._back:
            print(msg)

    async def send(self, src, dest, code, data=b'', prio=0):
        msg = BusMessage()
        msg.start_send()
        msg.src = src
        msg.dst = dest
        msg.code = code
        msg.send_data(data)

        await self._back.send(msg, prio)

    async def reply(self, msg, src=None,dest=None,code=None, data=b'', prio=0):
        if src is None:
            src=msg.dst
        if dest is None:
            dest = msg.src
        if code is None:
            code = 3  # standard reply
        await self.send(src,dest,code,data=data,prio=prio)

    async def handle_packet(self, msg):
        if msg.src == -4:
            if msg_dest == -4 and msg.code == 1: ## address assignment
                return await self._handle_assign(msg)
            return self.log.warning("Reserved 1: %r", msg)
        if msg.src < 0:
            if msg.dest >= 0 and msg.code == 4:
                return await self._handle_assign_reply(msg)
            if msg.dest == -4:
                return self.log.warning("Reserved 3: %r", msg)
        if msg.src >= 0 and msg.dest == -4:
            return await self._handle_broadcast(msg)
        if msg.command < 3:
            return await self._handle_directory(msg)
        if msg.command == 3:
            return await self._handle_reply(msg)
        if msg.command <= 7:
            return self.log.warning("Reserved 4: %r", msg)
        return await self._handle_direct(msg)

    async def _handle_assign(self, msg: BusMessage):
        m = msg.bytes
        mlen = (m[0] & 0xF) +1
        flags = m[0] >> 4
        err = 0

        async def reject(err):
            rm = bytes(((err<<4) | (mlen-1,))) + m[1:mlen+1]
            await self.reply(data=rm, src=self.id, dest=-4, code=1)  # no known flags yet


        if len(m)-1 < mlen:
            self.log.error("Too-short addr request %r",msg)
            return
        s = m[1:mlen+1]
        if flags:
            self.log.warning("Unknown addr req flags %r",msg)
            for n in range(4):
                if flags & (1<<n):
                    return await reject(4+n)
                    break

        rm = bytes((mlen-1,)) + m[1:mlen+1]
        try:
            o = self.with_serial(s)
        except NoFreeID:
            await reject(8)
            await self.run_verifier()
        else:
            rm = bytes(((o.__data is not None) << 4) | (mlen-1,)) + m[1:mlen+1]
            
            await self.reply(data=rm, dest=o.__reg_id, src=self.id, code=4)  # no known flags yet
            if o.__data is None:
                await self.q_w.put(NewDevice(obj))
            else:
                await self.q_w.put(OldDevice(obj))


    async def _handle_assign_reply(self, msg: BusMessage):
        """
        Some other server has assigned the address.

        TODO.
        """
        m = msg.bytes
        mlen = (m[0] & 0xF) +1
        flags = m[0] >> 4
        if len(m)-1 < mlen:
            self.log.error("Short addr reply %r",msg)
            return
        o = self.with_serial(s, msg.dest)
        if o.__data is None:
            await self.q_w.put(NewDevice(obj))
        elif o.__reg_id != msg.dest:
            await self.q_w.put(OldDevice(obj))


    async def _handle_broadcast(self, msg: BusMessage):
        await self.q_w.put(BroadcastMsg(msg))
        raise RuntimeError("Not implemented", msg)


    async def _handle_directory(self, msg: BusMessage):
        raise RuntimeError("Not implemented", msg)


    async def _handle_reply(self, msg: BusMessage):
        if self.dest == self.id:
            self.id2obj[self.src].has_result(msg.data)


    async def _handle_direct(self, msg: BusMessage):
        if self.dest == self.id:
            await self.q_w.put(DirectMsg(msg))


    async def handle_event(self, evt):
        if isinstance(evt, NewDevice):
            obj = evt.obj
            self.log.info("New device: %r", obj)
        elif isinstance(evt, NewDevice):
            obj = evt.obj
            self.log.info("Known device: %r", obj)
        else:
            raise RuntimeError("Not implemented", evt)


