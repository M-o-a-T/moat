"""
This module implements a basic MoatBus address controller.
"""

import trio
from contextlib import asynccontextmanager
import msgpack
from functools import partial
from dataclasses import dataclass

from ...backend import BaseBusHandler
from ...message import BusMessage, LongMessageError
from ..obj import Obj
from ...util import byte2mini, mini2byte, Processor
from ..server import NoFreeID, IDcollisionError

import logging
logger = logging.getLogger(__name__)

@dataclass
class aa_record:
    serial: bytes = None
    flags:int = 0
    t_continue:int = 0
    t_live:int = 0
    t_sleep:int = 0

    @classmethod
    def unpack(cls, msg, logger):
        self = cls()

        d = msg.data
        ls = (d[0] >> 4) + 1
        serial = d[1:ls+1]
        if len(serial) < ls:
            logger.error("Serial short %r",msg)
            return None
        flags = 0
        pos = ls+1
        try:
            if d[0] & 0x08:
                flags = d[pos]
                pos += 1

                if flags & 0x01:
                    self.t_continue = d[pos]
                    pos += 1
                if flags & 0x08:
                    self.t_live = d[pos]
                    self.t_sleep = d[pos+1]
                    pos += 2
            if len(d) != pos:
                raise LongMessageError(d)
        except IndexError:
            logger.error("Serial short %r",msg)
            return None
        except LongMessageError:
            logger.error("Serial long %r",msg)
            return None
        return self



    @property
    def packet(self):
        ls = len(self.serial)-1
        if not 0 <= ls <= 0x0F:
            raise RuntimeError("Serial too long: %r" %(serial,))
        ls <<= 4
        more = []
        flags = self.flags

        if self.t_continue:
            flags |= 0x01
        if self.t_live or self.t_sleep:
            flags |= 0x08
        if flags & 0x01:
            more.append(self.t_continue)
        if flags & 0x08:
            more.append(self.t_live)
            more.append(self.t_sleep)

        if flags:
            ls |= 0x04
            more.insert(0,flags)

        return bytes((ls,)) + self.serial + bytes(more)


class AddrControl(Processor):
    """
    Address controller.

    Basic usage::

        async with AddrControl(Controller) as server:
            async for evt in server:
                await handle_event(evt)
                await server.send_msg(some_message)

    Arguments:
      timeout: sent to the client for arbitrary reply delay, default 5 seconds.

    """
    CODE=0

    def __init__(self, server, dkv, timeout=5.0):
        self.logger = logging.getLogger("%s.%s" % (__name__, server.my_id))
        self.timeout = timeout
        super().__init__(server, 0)

    async def setup(self):
        await super().setup()
        await self.spawn(self._fwd)

    async def _fwd(self, *, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        with self.objs.watch() as w:
            async for evt in w:
                await self.put(evt)

    async def process(self, msg):
        """Code zero"""
        # All Code-0 messages must include a serial
        aa = aa_record.unpack(msg, logger=self.logger)
        if aa is None:
            return

        if msg.src == -4:  # broadcast
            if msg.dst == -4 and msg.code == 0:
                await self._process_request(aa)
            else:
                self.logger.warning("Reserved: %r",msg)
        elif msg.src == self.my_id:
            self.logger.error("Message from myself? %r",msg)
        elif msg.src < 0:  # server N
            if msg.dst == -4:  # All-device messages
                await self._process_nack(msg)
            elif msg.dst < 0:  # server N
                await self._process_inter_server(msg)
            else:  # client
                await self._process_reply(msg)
        else: # from client
            if msg.dst == -4:  # broadcast
                await self._process_client_nack(msg)
            elif msg.dst == self.my_id:  # server N
                await self._process_client_reply(msg.src, aa)
            elif msg.dst < 0:  # server N
                await self._process_client_reply_mon(msg)
            else:  # client
                await self._process_client_direct(msg)

    async def _process_reply(self, msg: BusMessage):
        """
        Some other server has assigned the address.

        TODO.
        """
        m = msg.bytes
        mlen = (m[0] & 0xF) +1
        flags = m[0] >> 4
        if len(m)-1 < mlen:
            self.logger.error("Short addr reply %r",msg)
            return
        o = self.with_serial(s, msg.dest)
        if o.__data is None:
            await self.q_w.put(NewDevice(obj))
        elif o.client_id != msg.dest:
            await self.q_w.put(OldDevice(obj))


    async def _process_request(self, aa):
        """
        Control broadcast>broadcast
        AA: request
        """
        serial, flags, timer = aa.serial, aa.flags, aa.t_continue

        async def accept(cid, code=0, timer=0):
            self.logger.info("Accept x%x for %d:%r", code, cid, serial)
            await self.send(src=self.my_id,dst=cid,code=0,data=build_aa_data(serial,code,timer))

        async def reject(err, dly=0):
            self.logger.info("Reject x%x for %r", err, serial)
            await self.send(src=self.my_id,dst=-4,code=0,data=build_aa_data(serial,err,dly))

        obj = self.objs.obj_serial(serial, create=False if flags & 0x02 else None)
        obj.polled = bool(flags & 0x04)

        if obj.client_id is None:
            await self.objs.register(obj)
        if timer:
            async def do_dly(obj):
                await trio.sleep(byte2mini(timer))
                await accept(obj.client_id,0)
            await self.spawn(do_dly,obj)
        else:
            await accept(obj.client_id,0)

    async def _process_inter_server(self, msg):
        """
        Inter-server sync for AA. Reserved.
        AA: nack
        """
        self.logger.debug("Not implemented: inter-server-sync %r", msg)

    async def _process_nack(self, msg):
        """
        Control server>broadcast
        AA: nack
        """
        self.logger.debug("Not implemented: server nack %r", msg)

    async def _process_client_nack(self, msg):
        """
        Control client>broadcast; NACK by client, addr collision
        """
        self.logger.warning("Not implemented: control_cb %r", msg)

    async def _process_client_reply(self, client, aa):
        """
        Client>server
        """
        serial, flags, timer = aa.serial,aa.flags,aa.t_continue

        objs = self.objs
        obj2 = None
        try:
            obj1 = objs.obj_client(client)
        except KeyError:
            obj1 = None
        else:
            if obj1 is not None:
                if obj1.serial == serial:
                    obj2 == obj1
                else:
                    self.logger.error("Conflicting serial: %d: new:%s known:%s", client, serial, obj.serial)
                    await objs.deregister(obj1)

        if obj2 is None:
            obj2 = objs.obj_serial(serial, create=None)

        if obj2.client_id is None:
            obj2.client_id = client
            await objs.register(obj2)
        elif obj2.client_id != client:
            self.logger.error("Conflicting IDs: new:%d known:%d: %s", client,obj.client_id,serial)
            await objs.deregister(obj2)
            await objs.register(obj2)

    async def _process_client_reply_mon(self, msg):
        self.logger.warning("Not implemented: reply_mon %r", msg)

    async def _process_client_direct(self, msg):
        """
        Control client>client
        """
        self.logger.warning("Not implemented: client_direct %r", msg)


    async def _handle_assign_reply(self, msg: BusMessage):
        """
        Some other server has assigned the address.

        TODO.
        """
        m = msg.bytes
        mlen = (m[0] & 0xF) +1
        flags = m[0] >> 4
        if len(m)-1 < mlen:
            self.logger.error("Short addr reply %r",msg)
            return
        o = self.get_serial(s, msg.dest)

