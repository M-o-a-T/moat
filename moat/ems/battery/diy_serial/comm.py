"""
Battery communications for diyBMS-MoaT messages
"""

from __future__ import annotations

#
import logging
from pprint import pformat

from moat.util import ValueEvent
from moat.ems.battery.errors import MessageError, MessageLost, NoSuchCell
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import (
    Lock,
    TimeoutError,  # noqa:A004
    sleep_ms,
    ticks_diff,
    ticks_ms,
    wait_for_ms,
)

from .packet import PacketHeader, replyClass

logger = logging.getLogger(__name__)


class BattComm(BaseCmd):
    """
    Communicator for our serial BMS.

    This app accepts calls with control packets, encodes and forwards them
    to the link, and returns the reply packets.
    """

    n_cells: int = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.t = ticks_ms()
        self.seq = 0
        self.waiting = [None] * PacketHeader.n_seq
        self.w_lock = Lock()
        self.retries = cfg.get("retry", 10)
        self.rate = cfg.get("rate", 2400)
        self.n_cells = cfg.get("n", 16)

    async def setup(self):  # noqa:D102
        await super().setup()
        self.comm = self.root.sub_at(self.cfg["comm"])

    async def task(self):  # noqa:D102
        self.set_ready()
        await self._read()

    async def cmd(self, p, s=None, e=None, bc: bool = False):
        """
        Send message(s) @p to the cells @s through @e.

        Returns the per-battery replies.
        """
        await self.wait_ready()

        err = None
        max_t = self.n_cells * 300 if self.n_cells else 5000
        if not isinstance(p, (list, tuple)):
            p = (p,)

        for _n in range(self.retries):
            try:
                return (await self._send(pkt=p, start=s, end=e, broadcast=bc, max_t=max_t))[1]
            except (TimeoutError, MessageLost) as exc:
                if err is None:
                    err = exc
        raise err from None

    async def _send(self, pkt, start=None, end=None, broadcast=False, max_t=5000):
        """
        Send a message to the cells.
        Returns the per-battery replies.

        May time out.
        """
        # "broadcast" means the request header is not deleted.
        # start=None requires broadcast.
        # end!=start and len(pkt)==1 requires broadcast IF the request packet
        # contains data.
        end  # noqa:B018

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
                    # TODO calculate worst-case delay
                    await wait_for_ms(10000, evt.wait)
                except TimeoutError:
                    # ugh, everything dead?
                    if self.waiting[seq] is evt:
                        self.waiting[seq] = None
                    raise

            # update self.seq only when the slot is empty
            self.seq = (self.seq + 1) % PacketHeader.n_seq
            logger.debug("REQ %r slot %d", pkt, seq)
            self.waiting[seq] = evt = ValueEvent()

            # We need to delay by whatever the affected cells add to the
            # message, otherwise the next msg might catch up
            # The 3 is start byte and length (1…2 bytes), the 2 is CRC.
            # The header et al. sizes are multiplied in because each slave delays
            # by the header size *and* it adds the reply.
            msg = h.encode_all(pkt)
            n_cells = h.cells + 1
            mlen = len(msg) + n_cells * (replyClass[h.command].S.size + h.S.size + 3) + 2

            # A byte needs ten bit slots to transmit. However, the modules'
            # baud rates can be slightly off, which increases the delay
            self.t = t + (10000 + 500 * n_cells) * mlen / self.rate
            await self.comm.sb(m=msg)

        try:
            res = await wait_for_ms(max_t, evt.get)
        except TimeoutError as exc:
            evt.set_error(exc)
            if self.waiting[seq] is evt:
                self.waiting[seq] = None
            raise
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
                hdr, msg = PacketHeader.decode(msg)
                pkt = hdr.decode_all(msg)
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
