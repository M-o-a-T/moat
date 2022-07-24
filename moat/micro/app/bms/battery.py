#
import asyncdbus.service as dbus
from asyncdbus.signature import Variant
from asyncdbus.constants import NameFlag
from pprint import pformat
from functools import cached_property

from moat.compat import CancelledError, sleep, sleep_ms, wait_for_ms, ticks_ms, ticks_diff, ticks_add, TimeoutError, Lock, TaskGroup
from moat.util import ValueEvent, combine_dict, attrdict
from moat.dbus import DbusInterface

from .cell import Cell
from .packet import *

import logging
logger = logging.getLogger(__name__)


class BatteryInterface(DbusInterface):
    def __init__(self, batt, dbus):
        self.batt = batt
        super().__init__(ctrl, dbus, f"/BMS/{}", "bms")

    def done(self):
        del self.batt
        super().done()

    @dbus.method()
    async def SetVoltage(self, data: 'd') -> 'b':
        # update the scale appropriately
        await self.batt.set_voltage(data)

    @dbus.signal()
    async def CellVoltageChanged(self) -> 'a(db)':
        """
        Send cell voltages and bypass flags
        """
        return [(c.voltage,c.in_balance) for c in self.batt.cells]

    @dbus.signal()
    async def VoltageChanged(self) -> 'd':
        """
        Send pack voltage
        """
        return [(c.voltage,c.in_balance) for c in self.cells]

    @dbus.signal()
    async def CellTemperatureChanged(self) -> 'a(vv)':
        """
        Return cell temperatures (load, battery)

        False if there is no value
        """
        F = lambda x: Variant('b', False) if x is None else Variant('d', x)

        return [(F(c.load_temp),F(c.batt_temp)) for c in self.batt.cells]

    @dbus.method()
    async def GetNCells(self) -> 'y':
        """
        Number of cells in this battery
        """
        return len(self.batt.cells)

    @dbus.method()
    async def GetName(self) -> 's':
        """
        Number of cells in this battery
        """
        return self.batt.name


class Battery:
    # global battery state, reported via MOAT callback
    u:float = None
    i:float = None
    w:float = None
    n_w:float = 0

    w_past:float = 0
    nw_past:float = 0

    chg_set:bool = None
    dis_set:bool = None

    def __init__(self, ctrl, cfg, gcfg, start, num):
        super().__init__("org.m_o_a_t.bms")

        self.name = cfg.name
        self.num = num
        self.ctrl = ctrl
        self.path = f"/bms/{self.num}"
        self.ready = 0

        try:
            self.bms = gcfg.apps[cfg.bms]
        except AttributeError:
            self.bms = attrdict()

        self.start = start
        self.end = start+cfg.n-1

        self.cfg = cfg
        self.gcfg = gcfg

        self.cells = []
        for c in range(cfg.n):
            try:
                ccfg = cfg.cells[c]
            except IndexError:
                ccfg = attrdict()
            ccfg = combine_dict(ccfg, cfg.default, cls=attrdict)
            cell = Cell(self, nr=self.start+c, path=f"/bms/{self.num}/{c}", cfg=ccfg, bcfg=self.cfg, gcfg=gcfg)
            self.ctrl.add_cell(cell)
            self.cells.append(cell)

    def __repr__(self):
        return f"‹Batt {self.path} u={self.u} i={self.i}›"

    @cached_property
    def cfg_path(self):
        return self.ctrl.cfgpath | "batteries" | self.batt.num

    async def run(self):
        dbus = self.ctrl.dbus

        await dbus.export(f'/bms/{self.num}',self)
        for c in self.cells:
            await c.export(self.ctrl.dbus)

        try:
            await self._run()
        finally:
            for v in self.cells:
                await c.unexport()
            await dbus.unexport(f'/bms/{self.num}')

    async def _run(self):
        async with TaskGroup() as tg:
            await tg.spawn(self._read_update)

            h,res = await self.send(RequestGetSettings())
            if len(res) != len(self.cells):
                raise RuntimeError(f"Battery {self.start}:{self.end}: found {len(res)} modules, not {len(self.cells)}")

            for c,r in zip(self.cells,res):
                r.to_cell(c)

            await tg.spawn(self.task_keepalive)
            await tg.spawn(self.task_voltage)
            await tg.spawn(self.task_cellvoltage)
            await tg.spawn(self.task_celltemperature)


    async def task_keepalive(self):
        n = 0
        try:
            t = self.bms.poll.k / 2.1
        except AttributeError:
            return
        while True:
            self.ctrl.req.send([self.cfg.bms,"live"])
            n += 1
            if n == 1:
                self.ready |= 0x01

            await sleep_ms(t)

    @property
    def is_ready(self):
        return self.ready == 0x0F


    async def task_voltage(self):
        """
        Periodically check the battery voltages
        """
        n = 0
        gen = 0
        while True:
            res = await self._req.send([self.cfg.bms,"info", gen=gen))
            gen = res.pop("gen", 0)
            self.update_global(**res)
            n += 1
            if n == 4:
                self.ready |= 0x08

            await sleep(self.cfg.t.voltage)


    async def task_cellvoltage(self):
        """
        Periodically check the cell voltages
        """
        n = 0
        while True:
            hdr,res = await self.send(RequestCellVoltage())
            chg = False
            for c,r in zip(self.cells,res):
                chg = r.to_cell(c) or chg
            if chg:
                await self.check_limits()
                await self._intf.CellVoltageChanged()
            n += 1
            if n == 3:
                self.ready |= 0x02

            await sleep(self.cfg.t.cellvoltage)


    async def check_limits(self):
        """
        Verify that the battery voltages are within spec.
        """
        chg_ok = True
        dis_ok = True
        off = False

        vsum = sum(c.voltage for c in self.cells)
        if abs(vsum-self.u) > vsum*0.02:
            logger.warning(f"Voltage doesn't match: reported {self.u}, sum {vsum}")

        if self.bms:
            if self.u >= self.bms.cfg.u.ext.max:
                logger.warning(f"{self} voltage high, no charging")
                chg_ok = False

            if self.u >= self.bms.cfg.u.max:
                off = True
                logger.error(f"{self} overvoltage, turned off")

            if self.u <= self.bms.cfg.u.ext.min:
                logger.warning(f"{self} voltage low, no discharging")
                dis_ok = False

            if self.u <= self.bms.cfg.u.min:
                off = True
                logger.error(f"{self} undervoltage, turned off")

        for c in self.cells:
            if c.voltage >= c.cfg.u.ext.max:
                chg_ok = False
                logger.warning(f"{c} voltage high, no charging")

            if c.voltage >= c.cfg.u.max:
                breakpoint()
                logger.error(f"{c} overvoltage, turned off")

            if c.voltage <= c.cfg.u.ext.min:
                dis_ok = False
                logger.warning(f"{c} voltage low, no discharging")

            if c.voltage <= c.cfg.u.min:
                off = True
                logger.error(f"{c} undervoltage, turned off")

        if off and self.is_ready:
            await self.ctrl.req.send([self.cfg.bms,"rly"], st=False)

        if self.chg_set != chg_ok or self.dis_set != dis_ok:
            # send limits to BMS in mplex
            await self.ctrl.req.send(["local",self.cfg.bms,"cell"], okch=chg_ok, okdis=dis_ok)
            self.chg_set = chg_ok
            self.dis_set = dis_ok




    async def task_celltemperature(self):
        """
        Periodically check the cell temperatures
        """
        n = 0
        while True:
            hdr,res = await self.send(RequestCellTemperature())
            chg = False
            for c,r in zip(self.cells,res):
                chg = r.to_cell(c) or chg
            if chg:
                await self._intf.TemperatureChanged()
            n += 1
            if n == 3:
                self.ready |= 0x04

            await sleep(self.cfg.t.celltemperature)


    async def send(self, pkt, start=None, end=None, **kw):
        """
        Send a message to "my" cells.
        """
        if start is None:
            start = self.start
        if end is None:
            end = self.end
        return await self.ctrl.send(pkt,start=start, end=end, **kw)

    async def _read_update(self):
        try:
            bms = self.cfg.bms
        except AttributeError:
            return  # no global BMS today
        while True:
            msg = await self.ctrl.req.send(["local",self.cfg.bms,"data"])
            await self.update_global(**msg)


    async def update_global(self, u=None,i=None,n=None,w=None,**kw):
        if u is not None:
            self.u = u

        if i is not None:
            self.i = i

        if w is not None:
            if n < self.n_w:
                self.w_past += self.w
                self.nw_past += self.n_w
            self.w = w
            self.n_w = n

    async def set_voltage(self, val):
        # TODO move this to a config update handler
        adj = (data - self.cfg.u.offset) / (self.u - self.cfg.u.offset)
        self.cfg.u.scale *= adj
        await self.ctrl.send(["sys","cfg"], cfg=attrdict()._update(("apps",self.name,"cfg","u"), {"scale":self.cfg.u.scale}))

        self.u = data
        return True

