"""
Serial packet forwarder

Configuration::

    uart: N  # number on the client
    tx: PIN
    rx: PIN
    baud: 9600
    max:  # packets
      len: N
      idle: MSEC
    start: NUM

"""

import logging

import anyio
from moat.util import Queue  # pylint:disable=no-name-in-module

from ._base import BaseAppCmd

logger = logging.getLogger(__name__)


class SerialCmd(BaseAppCmd):
    "Command wrapper for serial connection"
    cons_warn = False

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.qr = Queue(99)
        self.qp = Queue(99)

    async def cmd_pkt(self, data):
        "send a packet"
        await self.send([self.name, "pkt"], data)

    async def cmd_raw(self, data):
        "send raw data"
        await self.send([self.name, "raw"], data)

    async def cmd_in_pkt(self, data):
        "receive+queue a packet"
        try:
            self.qp.put_nowait(data)
        except anyio.WouldBlock:
            logger.error("Serial packet %s: too many unprocessed packets", self.name)
            raise

    async def cmd_in_raw(self, data):
        "receive+queue raw data"
        try:
            self.qr.put_nowait(data)
        except anyio.WouldBlock:
            if not self.cons_warn:
                self.cons_warn = True
                logger.warning("Serial raw %s: console data overflow", self.name)
        else:
            self.cons_warn = False

    async def loc_pkt(self):
        "get packet from queue"
        return await self.qp.get()

    async def loc_raw(self):
        "get raw data from queue"
        # retrieve the next raw serial message
        return await self.qr.get()
