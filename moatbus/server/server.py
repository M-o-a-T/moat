"""
This module implements the basics for a bus server.
"""

import trio
from contextlib import asynccontextmanager

from ..backend import BaseBusHandler
from ..message import BusMessage
from .obj import get_obj, Obj
from ..util import byte2mini, CtxObj

import msgpack
from functools import partial

packer = msgpack.Packer(strict_types=False, use_bin_type=True, #default=_encode
        ).pack
unpacker = partial(
    msgpack.unpackb, raw=False, use_list=False, # object_pairs_hook=attrdict, ext_hook=_decode
)

import logging
logger = logging.getLogger(__name__)

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

class Server(CtxObj):
    """
    Bus server.

    Basic usage::

        async with Server(backend, id) as server:
            async for evt in server:
                await handle_event(evt)
    """
    _check_task = None

    def __init__(self, backend:BaseBusHandler, id=1):
        if id<1 or id>3:
            raise RuntimeError("My ID must be within 1…3")
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
        Register a bus object.

        This should only be called from `obj.register`.
        """
        self.deregister(obj)
        # Happens when we observe another server's assignment
        new_id = obj.client_id
        if new_id is None:
            new_id = self.get_free_id()

        self.ser2obj[obj.serial] = obj
        self.id2obj[new_id] = obj
        obj.client_id = new_id
        obj.__data = None

    def bus_id(self, obj):
        return obj.client_id

    def deregister(self, obj):
        """
        De-register a bus object.

        This should only be called from `obj.deregister`.
        """
        try:
            # Order is important.
            del self.ser2obj[obj.serial]
            del self.id2obj[obj.client_id]
            del obj.client_id
        except (AttributeError,KeyError):
            pass

    def __aiter__(self):
        return self

    def __anext__(self):
        return self.q_r.__anext__()

    async def sync_in(self, client):
        """
        Check if a sync message has arrived on the bus; if so, wait until
        the change described in it has arrived on the client
        """
        pass  # TODO

    async def sync_out(self, client, chain):
        """
        Send a "this chain must have arrived at your node to proceed"
        message to the bus
        """
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

    async def _reader(self, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        async for msg in self._back:
            print(msg)
            if msg.code == 0:
                await self._handle_server(msg)
            # otherwise dispatch

    async def _handle_server(self, msg):
        if msg.src == -4:  # broadcast
            if msg.dst == -4 and msg.code == 0:
                await self._hs_control_bb(msg)
            else:
                self.logger.warning("Reserved: %r",msg)
        elif msg.src < 0:  # server N
            if msg.dst == -4:  # All-device messages
                if msg.code == 0:
                    await self._hs_control_sb(msg)
                else:
                    self.logger.warning("Reserved: %r",msg)
            elif msg.dst < 0:  # server N
                await self._hs_inter_server(msg)
            else:  # client
                if msg.code == 0:
                    await self._hs_control_sc(msg)
                else:
                    self.logger.warning("Not for us: %r",msg)
        else: # client
            if msg.dst == -4:  # broadcast
                if msg.code == 0:
                    await self._hs_control_cb(msg)
                elif code <= 7:
                    self.logger.warning("Reserved: %r",msg)
                else:
                    await self._hs_broadcast(msg)
            elif msg.dst < 0:  # server N
                if msg.code == 0:
                    await self._hs_control_cs(msg)
                elif msg.code == 1:
                    await self._hs_client_alert(msg)
                elif msg.code == 2:
                    await self._hs_client_read_reply(msg)
                elif msg.code == 3:
                    await self._hs_client_write_reply(msg)
                else:
                    self.logger.warning("Reserved: %r",msg)

            else:  # client
                await self._hs_direct(msg)

    async def _hs_control_bb(self, msg):
        """
        Control broadcast>broadcast
        AA: request
        """
        d = msg.data
        if not len(d):
            self.logger.warning("Not implemented: control_bb %r", msg)
            return
        fn = d[0]>>5
        if fn == 0: ## AA
            await self._hs_aa_request(msg)
        else:
            self.logger.warning("Not implemented: control_bb %r", msg)

    async def _hs_control_sc(self, msg):
        """
        Control server>client
        AA: ack
        """
        self.logger.warning("Not implemented: control_sc %r", msg)

    async def _hs_control_sb(self, msg):
        """
        Control server>broadcast
        AA: nack
        """
        self.logger.warning("Not implemented: control_sb %r", msg)

    async def _hs_control_cb(self, msg):
        """
        Control client>broadcast; poll data request
        """
        self.logger.warning("Not implemented: control_cb %r", msg)

    async def _hs_control_cs(self, msg):
        """
        Control client>server; replies to _SC
        """
        self.logger.warning("Not implemented: control_cs %r", msg)

    async def _hs_sync(self, msg):
        """
        DistKV sync
        """
        src = msg.src
        msg = unpacker(msg.data)
        self.logger.info("Sync from %d: %r", src, msg)
        pass  # TODO

    async def _hs_aa_request(self, msg):
        d = msg.data

        ls = (d[0]&0xF)+1
        serial = d[1:ls+1]
        try:
            flags = d[ls+1]
        except IndexError:
            self.logger.error("Serial short %r",msg)
            return

        async def accept(cid, code=0, timer=0):
            self.logger.info("Accept x%x for %d:%r", code, cid, serial)
            if timer:
                timer=byte((timer,))
                code |= 0x80
            else:
                timer = b''
            d = bytes(((0x10 if code else 0x00)+len(serial)-1,)) + serial + (bytes((code,)) if code else b'') + timer
            await self.send(src=self.id,dst=cid,code=0,data=d)

        async def reject(err, dly=0):
            self.logger.info("Reject x%x for %r", err, serial)
            if dly:
                err |= 0x80
            d = msg.data[0:ls+1] + (bytes((err,dly)) if dlx else bytes((err,)))
            await self.send(src=self.id,dst=-4,code=0,data=d)

        obj = self.with_serial(serial)
        obj.polled = bool(flags & 0x20)
        if flags & 0x80:
            td = d[ls+2]
            await trio.sleep(byte2mini(td))

        if flags & 0x40: # known
            if serial in self.ser2obj:
                await accept(0x40)
        try:
            obj = get_obj(serial, create=False if flags&0x40 else None)
        except NoFreeID:
            await reject(0x10)  # no free address: wait for Poll
            # TODO start polling to find dead clients
        else:
            await accept(obj.client_id,0)
            if obj.is_new:
                obj.is_new = False
                await obj.new_adr()

    async def _hs_aa_reject(self, msg):
        """
        Some other server has rejected a client.
        """
        pass

    async def _hs_aa_response(self, msg):
        """
        Some other server has accepted a client.

        We should get that information via the network.
        """
        pass

    async def _hs_control_all(self, msg):
        """
        Some other server has sent a control-all message

        We should get that information via the network.
        """
        pass

    async def _hs_control_one(self, msg):
        """
        Some other server has sent a control-one message

        We should get that information via the network.
        """
        pass

    async def _hs_client_poll(self, msg):
        try:
            obj = self.id2obj[msg.src]
        except KeyError:
            self.logger.warning("Obj %d sends poll but is not known", msg.src)
            return
        if not obj.polled:
            self.logger.warning("Obj %d/%r sends poll but is not polled", msg.src, obj)
            obj.polled = True
        d = msg.data
        tl = d[0] & 0xF
        if tl & 0x8:
            tl = (-1 & ~0x7) | (tl & 0x7)
        obj.poll_end = time.monotonic() + 2**tl
        await obj.poll_start(2**tl)

    async def _hs_client_poll_req(self, msg):
        """
        Some other server has sent a poll-request message

        We should not be interested.
        """
        pass

    async def send(self, src, dst, code, data=b'', prio=0):
        msg = BusMessage()
        msg.start_send()
        msg.src = src
        msg.dst = dst
        msg.code = code
        msg.add_data(data)

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
            
            await self.reply(data=rm, dest=o.client_id, src=self.id, code=4)  # no known flags yet
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
        elif o.client_id != msg.dest:
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


