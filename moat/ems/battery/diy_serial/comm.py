"""
Battery communications for diyBMS-MoaT messages
"""

from __future__ import annotations
#
import logging
from contextlib import asynccontextmanager
from functools import cached_property
from pprint import pformat

from moat.util import ValueEvent, attrdict, combine_dict

from moat.micro.compat import (
    Event,
    Lock,
    TimeoutError,
    sleep_ms,
    ticks_diff,
    ticks_ms,
    wait_for_ms,
)

from moat.micro.cmd.base import BaseCmd

from ..errors import MessageLost, MessageError, NoSuchCell
from .packet import *

logger = logging.getLogger(__name__)


class BattComm(BaseCmd):
    """
    Communicator for our serial BMS.
    """
    n_cells:int = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.t = ticks_ms()
        self.seq = 0
        self.waiting = [None] * PacketHeader.n_seq
        self.w_lock = Lock()
        self.retries = cfg.get("retry", 10)
        self.rate = cfg.get("rate", 2400)
        self.n_cells = cfg.get("nr", 6)

    async def setup(self):
        await super().setup()
        self.comm = self.root.sub_at(*self.cfg["comm"])

    async def task(self):
        self.set_ready()
        await self._read()

    async def cmd(self, p, s=None, e=None, bc:bool=False):
        """
        Send message(s) @p to the cells @s through @e.
        Returns the per-battery replies.
        """

        err = None
        for n in range(self.retries):
            try:
                return await wait_for_ms(self.n_cells * 300 if self.n_cells else 10000,
                    self._send, pkt=p, start=s, end=e, broadcast=bc)
            except (TimeoutError, MessageLost) as exc:
                if err is None:
                    err = exc
        raise err from None

    async def _send(self, pkt, start=None, end=None, broadcast=False):
        """
        Send a message to the cells.
        Returns the per-battery replies.

        May time out.
        """
        # "broadcast" means the request data is not deleted.
        # start=None requires broadcast.
        # end!=start and len(pkt)==1 requires broadcast IF the packet
        # actually contains data.

        h = PacketHeader(start=start or 0, broadcast=broadcast)

        async with self.w_lock:
            h.sequence = seq = self.seq

            # delay for the previous message
            t = ticks_ms()
            td = ticks_diff(self.t, t)
            if td > 0:
                await sleep_ms(td)

            evt = self.waiting[seq]
            if evt is not None:
                # wait for the previous request to complete
                logger.warning("Wait for slot %d", seq)
                try:
                    await wait_for_ms(5000, evt.wait)
                except TimeoutError:
                    # ugh, everything dead?
                    self.waiting[seq] = None
                    raise

            # update self.seq only when the slot is empty
            self.seq = (self.seq + 1) % PacketHeader.n_seq
            logger.debug("REQ %r slot %d", pkt, seq)
            self.waiting[seq] = evt = ValueEvent()

            # We need to delay by whatever the affected cells add to the
            # message, otherwise the next msg might catch up
            msg = h.encode_all(pkt)
            n_cells = h.cells + 1
            mlen = len(msg) + n_cells * (replyClass[h.command].S.size + h.S.size + 4)

            self.t = t + 10000 * mlen / self.rate
            await self.comm.sb(m=msg)

        res = await wait_for_ms(5000, evt.get)
        logger.debug("RES %s", pformat(res))
        return res

    async def _read(self):
        # task to read serial data from the Serial subsystem
        def set_err(seq, err):
            n, self.waiting[seq] = self.waiting[seq], None
            if n is not None:
                n.set_error(err)

        xseq = -1
        while True:
            msg = await self.comm.rb()

            try:
                hdr, pkt = PacketHeader.decode(msg)
            except MessageError:
                logger.warning("Cannot decode: %r", msg)
                continue

            while True:
                xseq = (xseq + 1) % PacketHeader.n_seq
                if xseq == hdr.sequence:
                    break
                set_err(xseq, MessageLost())

            if not hdr.seen:
                set_err(xseq, NoSuchCell(hdr.start))
                continue

            evt, self.waiting[xseq] = self.waiting[xseq], None
            if evt is not None:
                logger.debug("IN %r", hdr)
                evt.set((hdr, pkt))
            else:
                logger.warning("IN? %r", hdr)
