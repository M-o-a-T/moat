"""
Test implementation of something that may or may not behave like a battery
"""

from __future__ import annotations

import logging
from functools import partial

from moat.util import attrdict
from moat.micro.app.bms._test.diy_packet import PacketHeader, replyClass
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import Queue, TaskGroup

logger = logging.getLogger(__name__)


class _CellSim(BaseCmd):
    # needs "ctrl" and "cell" attributes
    ctrl = None
    cell = None

    async def task(self):
        while True:
            msg = await self.ctrl.xrb()
            hdr, msg = PacketHeader.decode(msg)
            addr = hdr.hops
            hdr.hops += 1
            if hdr.start > addr or hdr.start + hdr.cells < addr:
                # not for us
                await self.ctrl.xsb(m=hdr.encode_one(msg))
                continue

            hdr.seen = True

            pkt, msg = hdr.decode_one(msg)
            logger.debug("MSG %r %r", hdr, pkt)
            if pkt is not None:
                await pkt.to_cell(self.cell)
            rsp = replyClass[hdr.command]()
            await rsp.from_cell(self.cell)
            await self.ctrl.xsb(m=hdr.encode_one(msg, rsp))


class CellSim(_CellSim):
    """
    Back-end to simulate a single cell.

    This is a background app. It reads byte blocks from the loopback app at @ctrl,
    analyzes them, and replies according to the cell app at @cell.
    """

    async def setup(self):
        await super().setup()
        self.cell = self.root.sub_at(self.cfg["cell"])
        self.ctrl = self.root.sub_at(self.cfg["ctrl"])

    async def task(self):
        self.set_ready()
        await super().task()


class _SingleCellSim(_CellSim):
    """
    Interface for a cell in a series, configured via CellsSim.
    """

    def __init__(self, cell, ctrl):
        self.cell = cell
        self.ctrl = ctrl


class CellsSim(_CellSim):
    """
    Back-end to simulate multiple cells.

    Config:
        n: number of cells
        ctrl: LoopLink taking to them
        cell: path to the array of Cell objects this app shall control
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.n_cells = cfg["n"]

    async def setup(self):
        await super().setup()
        self.ctrl = self.root.sub_at(self.cfg["ctrl"])

    async def task(self):
        cell = self.cfg["cell"]

        def _mput(q, m):
            return q(m)

        async with TaskGroup() as tg:
            q = None
            for i in range(self.n_cells):
                c = attrdict()
                if i == 0:  # first
                    c.xrb = self.ctrl.xrb
                else:
                    c.xrb = q.get
                if i < self.n_cells - 1:
                    q = Queue()
                    c.xsb = partial(_mput, q.put)
                else:  # last
                    c.xsb = self.ctrl.xsb

                cp = self.root.sub_at(cell / i)
                sim = _SingleCellSim(cp, c)
                await tg.spawn(sim.task)
            self.set_ready()
