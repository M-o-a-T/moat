#
from __future__ import annotations

import anyio
import contextlib
import logging
from functools import cached_property
from pprint import pformat

import asyncdbus.service as _dbus
from victron.dbus.utils import wrap_dbus_dict

from moat.util import ValueEvent
from moat.dbus import DbusInterface, DbusName
from moat.util.compat import (
    Event,
    Lock,
    TaskGroup,
    TimeoutError,
    sleep_ms,
    ticks_diff,
    ticks_ms,
    wait_for_ms,
)

from . import MessageLost, SpuriousData
from .battery import Battery
from .packet import *
from .victron import BatteryState

logger = logging.getLogger(__name__)


class ControllerInterface(DbusInterface):
    def __init__(self, ctrl, dbus):
        self.ctrl = ctrl
        super().__init__(dbus, "/bms", "bms")

    def done(self):
        del self.ctrl
        super().done()

    @_dbus.method()
    async def GetNBatteries(self) -> y:
        """
        Number of batteries on this controller
        """
        return len(self.ctrl.batt)

    @_dbus.method()
    async def GetVoltages(self) -> "aa{sd}":
        """
        Voltage data for all batteries
        """
        return [b.get_voltages() for b in self.ctrl.batt]

    @_dbus.method()
    async def GetCurrents(self) -> ad:
        """
        Voltage data for all batteries
        """
        return [b.current for b in self.ctrl.batt]

    @_dbus.method()
    async def GetConfig(self) -> "a{sv}":
        """
        Configuration data
        """
        # return [ [ wrap_dbus_value(b.cfg), wrap_dbus_value(b.ccfg) ]  for b in self.ctrl.batt ]
        return wrap_dbus_dict(self.ctrl.cfg)

    @_dbus.method()
    async def GetWork(self, poll: b, clear: b) -> "aa{sd}":
        """
        Return work done
        """
        if poll:
            for b in self.ctrl.batt:
                await b.update_work()
        w = await self.ctrl.get_work(clear)
        return w


class Controller:
    """
    Main controller for our BMS.

    TODO *really* support more than one battery
    """

    victron = None

    def __init__(self, cmd, name, cfg, gcfg):
        self.name = name
        self.cmd = cmd
        self.cfg = cfg
        self.gcfg = gcfg

        self.batt = []
        self.cells = []

        # data to talk to the cell modules
        self.seq = 0
        self.t = ticks_ms()
        self.w_lock = Lock()
        self.baud = gcfg[cfg.serial].baud
        self.waiting = [None] * 8

        n = 0
        if "batteries" in cfg:
            for i, b in enumerate(cfg.batteries):
                batt = Battery(self, b.batt, cfg.cell, gcfg, n, i)
                self.batt.append(batt)
                n += b.n
        else:
            batt = Battery(self, cfg.batt, cfg.cell, gcfg, n, None)
            self.batt.append(batt)
            n += cfg.batt.n

        self.victron = BatteryState(self)

    def clear_work(self):
        for b in self.batt:
            b.clear_work()

    async def get_work(self, clear: bool = False):
        res = []
        for b in self.batt:
            res.append(b.work)
            if clear:
                b.clear_work()
        return res

    async def config_updated(self):
        await self.victron.config_updated()
        for b in self.batt:
            await b.config_updated()

    def add_cell(self, cell):
        self.cells.append(cell)

    def cfg_name(self):
        return self.name

    @property
    def busname(self):
        return self.name

    @cached_property
    def cfg_path(self):
        return Path("bms", self.name)

    async def run(self, dbus):
        self._dbus = dbus

        try:
            async with ControllerInterface(self, dbus) as intf, TaskGroup() as tg:
                self._intf = intf

                evt = Event()
                await tg.spawn(self.victron.run, dbus, evt, _name="bms_vrun")
                await evt.wait()

                evt = Event()
                await tg.spawn(self._run, evt, _name="bms_crun")
                await evt.wait()

                # Everything is up and running.
                # *Now* register the name.
                async with DbusName(dbus, f"com.victronenergy.battery.{self.busname}"):
                    await anyio.sleep(10)
                    await self.victron.update_boot()

                    while True:
                        await anyio.sleep(99999)

        finally:
            with contextlib.suppress(AttributeError):
                del self._dbus
            with contextlib.suppress(AttributeError):
                del self._intf

    @property
    def dbus(self):
        return self._dbus

    @property
    def req(self):
        return self.cmd.request

    @property
    def intf(self):
        return self._intf

    async def _run(self, evt):
        async with TaskGroup() as tg:
            await tg.spawn(self._read, _name="bms_cread")

            evts = []
            for b in self.batt:
                e = Event()
                await tg.spawn(b.run, e, _name="bms_batt")
                evts.append(e)
            for e in evts:
                await e.wait()

            evt.set()
            del evts

    async def send(self, *a, **k):
        """
        Send a message to the cells.
        Returns the per-battery replies.

        Retries a few times before erroring out.
        """

        err = None
        for _n in range(10):
            try:
                with anyio.fail_after(len(self.cells) / 3 if self.cells else 10):
                    return await self._send(*a, **k)
            except (TimeoutError, MessageLost) as e:
                if err is None:
                    err = e
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

        if not isinstance(pkt, (list, tuple)):
            pkt = (pkt,)
        h = PacketHeader(command=pkt[0].T, start=start or 0, broadcast=broadcast)
        for p in pkt[1:]:
            if h.command != p.T:
                raise ValueError("Needs same type, not %s vs %s", pkt[0], p)

        if start is None or broadcast:
            if len(pkt) != 1 or not broadcast:
                raise RuntimeError("Broadcast means one message")
            h.cells = MAXCELLS - 1
        elif end is not None:
            h.cells = end - start
            if pkt[0].S.size > 0 and len(pkt) != h.cells + 1:
                raise ValueError(
                    "Wrong packet count, %d vs %d for %s" % (len(pkt), h.cells + 1, pkt[0]),
                )
        else:
            h.cells = len(pkt) - 1
        msg = b"".join(p.to_bytes() for p in pkt)

        async with self.w_lock:
            t = ticks_ms()
            td = ticks_diff(self.t, t)
            if td > 0:
                await sleep_ms(td)

            h.sequence = seq = self.seq
            evt = self.waiting[seq]
            if evt is not None:
                # wait for prev request to complete
                logger.warning("Wait for slot %d", seq)
                try:
                    await wait_for_ms(5000, evt.wait)
                except TimeoutError:
                    # ugh, everything dead?
                    self.waiting[seq] = None
                    raise

            # update self.seq only when the slot is empty
            self.seq = (self.seq + 1) % 8
            logger.debug("REQ %r slot %d", pkt, seq)
            self.waiting[seq] = evt = ValueEvent()

            # We need to delay by whatever the affected cells add to the
            # message, otherwise the next msg might catch up
            msg = h.to_bytes() + msg
            n_cells = h.cells + 1
            mlen = len(msg) + n_cells * (replyClass[h.command].S.size + h.S.size + 4)

            self.t = t + 10000 * mlen / self.baud
            await self.cmd.send([self.cfg.serial, "send"], data=msg)

        res = await wait_for_ms(5000, evt.get)
        logger.debug("RES %s", pformat(res))
        return res

    async def _read(self):
        # task to read serial data from the Serial subsystem
        def set_err(seq, err):
            n, self.waiting[seq] = self.waiting[seq], None
            if n is not None:
                n.set_error(err)

        xseq = 0
        while True:
            msg = await self.cmd.send(["local", self.cfg.serial, "pkt"])
            # TODO set up a subscription mechanism

            off = PacketHeader.S.size
            hdr = PacketHeader.from_bytes(msg[0:off])
            while xseq != hdr.sequence:
                set_err(xseq, MessageLost())
                xseq = (xseq + 1) & 0x07
            if not hdr.seen:
                set_err(hdr.sequence, NoSuchCell(hdr.start))
                continue
            RC = replyClass[hdr.command]
            RCL = RC.S.size
            pkt = []
            if hdr.broadcast:
                # The request header has not been deleted,
                # so we need to skip it
                off += requestClass[hdr.command].S.size
            if RCL:
                while off < len(msg):
                    if off + RCL > len(msg):
                        break  # incomplete
                    pkt.append(RC.from_bytes(msg[off : off + RCL]))
                    off += RCL
            if off != len(msg):
                set_err(hdr.sequence, SpuriousData(msg))
                continue

            evt, self.waiting[hdr.sequence] = self.waiting[hdr.sequence], None
            if evt is not None:
                logger.debug("IN %r", hdr)
                evt.set((hdr, pkt))
            else:
                logger.warning("IN? %r", hdr)
