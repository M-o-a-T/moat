"""
This module implements a basic MoatBus address controller.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import trio

from moat.bus.message import BusMessage, LongMessageError
from moat.bus.server.control.addr import aa_record, build_aa_data
from moat.bus.util import Processor, byte2mini, mini2byte

logger = logging.getLogger(__name__)


@dataclass
class poll_cp_record:
    """
    client ping
    """

    flags: int = 0
    t_live: int = 0
    t_sleep: int = 0

    @classmethod
    def unpack(cls, msg, logger):  # noqa:D102
        self = cls()

        d = msg.data
        pos = 1
        try:
            if d[0] & 0x08:
                self.t_live = d[pos]
                pos += 1
            if d[0] & 0x10:
                self.t_sleep = d[pos + 1]
            if len(d) != pos:
                raise LongMessageError(d)
        except IndexError:
            logger.error("Serial short %r", msg)
            return None
        except LongMessageError:
            logger.error("Serial long %r", msg)
            return None
        return self

    @property
    def packet(self):  # noqa:D102
        ls = len(self.serial) - 1
        if not 0 <= ls <= 0x0F:
            raise RuntimeError(f"Serial too long: {self.serial!r}")
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
            more.insert(0, flags)

        return bytes((ls,)) + self.serial + bytes(more)


class PollControl(Processor):
    """
    Address controller.

    Basic usage::

        async with PollControl(Controller) as server:
            async for evt in server:
                await handle_event(evt)
                await server.send_msg(some_message)

    Arguments:
      interval: poll interval, default 100 seconds.
      timeout: poll reply timeout, default 5 seconds.

    """

    CODE = 1

    def __init__(self, server, dkv, interval=100, timeout=5):
        dkv  # noqa:B018
        self.logger = logging.getLogger(f"{__name__}.{server.my_id}")
        self.interval = interval
        self.timeout = timeout
        super().__init__(server, 0)

    async def setup(self):  # noqa:D102
        await super().setup()
        await self.spawn(self._poller)
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
                self.logger.warning("Reserved: %r", msg)
        elif msg.src == self.my_id:
            self.logger.error("Message from myself? %r", msg)
        elif msg.src < 0:  # server N
            if msg.dst == -4:  # All-device messages
                await self._process_nack(msg)
            elif msg.dst < 0:  # server N
                await self._process_inter_server(msg)
            else:  # client
                await self._process_reply(msg)
        else:  # from client
            if msg.dst == -4:  # broadcast
                await self._process_client_nack(msg)
            elif msg.dst == self.my_id:  # server N
                await self._process_client_reply(msg.src, self.serial, 0, 0) # XXX flags, timer
            elif msg.dst < 0:  # server N
                await self._process_client_reply_mon(msg)
            else:  # client
                await self._process_client_direct(msg)

    async def _process_reply(self, msg: BusMessage):
        """
        Some other server has assigned the address.

        TODO.
        """
        raise NotImplementedError
#       m = msg.bytes
#       mlen = (m[0] & 0xF) + 1
#       m[0] >> 4
#       if len(m) - 1 < mlen:
#           self.logger.error("Short addr reply %r", msg)
#           return
#       o = self.with_serial(s, msg.dest)
#       if o.__data is None:
#           await self.q_w.put(NewDevice(obj))
#       elif o.client_id != msg.dest:
#           await self.q_w.put(OldDevice(obj))

    async def _process_request(self, aa):
        """
        Control broadcast>broadcast
        AA: request
        """
        serial, flags, timer = aa.serial, aa.flags, aa.t_continue

        async def accept(cid, code=0, timer=0):
            self.logger.info("Accept x%x for %d:%r", code, cid, serial)
            await self.send(
                src=self.my_id,
                dst=cid,
                code=0,
                data=build_aa_data(serial, code, timer),
            )

        async def reject(err, dly=0):
            self.logger.info("Reject x%x for %r", err, serial)
            await self.send(src=self.my_id, dst=-4, code=0, data=build_aa_data(serial, err, dly))

        obj = self.objs.obj_serial(serial, create=False if flags & 0x02 else None)
        obj.polled = bool(flags & 0x04)

        if obj.client_id is None:
            await self.objs.register(obj)
        if timer:

            async def do_dly(obj):
                await trio.sleep(byte2mini(timer))
                await accept(obj.client_id, 0)

            await self.spawn(do_dly, obj)
        else:
            await accept(obj.client_id, 0)

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

    async def _process_client_reply(self, client, serial, flags, timer):
        """
        Client>server
        """
        flags, timer  # noqa:B018
        objs = self.objs
        obj2 = None
        try:
            obj1 = objs.obj_client(client)
        except KeyError:
            obj1 = None
        else:
            if obj1 is not None:
                if obj1.serial == serial:
                    obj2 = obj1
                else:
                    self.logger.error(
                        "Conflicting serial: %d: new:%s known:%s",
                        client,
                        serial,
                        obj1.serial,
                    )
                    await objs.deregister(obj1)

        if obj2 is None:
            obj2 = objs.obj_serial(serial, create=None)

        if obj2.client_id is None:
            obj2.client_id = client
            await objs.register(obj2)
        elif obj2.client_id != client:
            self.logger.error(
                "Conflicting IDs: new:%d known:%d: %s",
                client,
                obj2.client_id,
                serial,
            )
            await objs.deregister(obj2)
            await objs.register(obj2)

    async def _process_client_reply_mon(self, msg):
        self.logger.warning("Not implemented: reply_mon %r", msg)

    async def _process_client_direct(self, msg):
        """
        Control client>client
        """
        self.logger.warning("Not implemented: client_direct %r", msg)

    async def _poller(self, *, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        await trio.sleep(1)
        while True:
            await self._send_poll()
            await trio.sleep(self.interval)

    async def _send_poll(self):
        """
        Send a poll request

        The interval is currently hardcoded to 5 seconds.
        """
        await self.send(self.my_id, -4, 0, bytes((0x09, mini2byte(self.timeout))))

    async def _handle_assign_reply(self, msg: BusMessage):
        """
        Some other server has assigned the address.

        TODO.
        """
        raise NotImplementedError
#       m = msg.bytes
#       mlen = (m[0] & 0xF) + 1
#       m[0] >> 4
#       if len(m) - 1 < mlen:
#           self.logger.error("Short addr reply %r", msg)
#           return
#       self.get_serial(s, msg.dest)
