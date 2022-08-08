#
import asyncdbus.service as dbus
from asyncdbus.signature import Variant
from asyncdbus.constants import NameFlag
from pprint import pformat
from functools import cached_property

from moat.compat import CancelledError, sleep, sleep_ms, wait_for_ms, ticks_ms, ticks_diff, ticks_add, TimeoutError, Lock, TaskGroup, Event
from moat.util import ValueEvent, combine_dict, attrdict
from moat.dbus import DbusInterface

from .cell import Cell
from .packet import *
from .. import ConfigError

import logging
logger = logging.getLogger(__name__)

def _t(x):
    if x is None:
        return -1000
    return x

class BatteryInterface(DbusInterface):
	def __init__(self, batt, dbus):
		self.batt = batt
		super().__init__(dbus, f"/bms/{self.batt.num or 0}", "bms")

	def done(self):
		del self.batt
		super().done()

	@dbus.method()
	def GetVoltage(self) -> 'd':
		return self.batt.voltage

	@dbus.method()
	async def Identify(self) -> 'b':
		h,_res = await self.batt.send(RequestIdentifyModule())
		return h.seen
	
	@dbus.method()
	def GetVoltages(self) -> 'a(db)':
		return [(c.voltage,c.in_balance) for c in self.batt.cells]

	@dbus.method()
	def GetTemperatures(self) -> 'a(dd)':
		return [(_t(c.load_temp), _t(c.batt_temp)) for c in self.batt.cells]

	@dbus.method()
	async def SetVoltage(self, data: 'd') -> 'b':
		# update the scale appropriately
		await self.batt.set_voltage(data)
		return True

	@dbus.method()
	def GetCurrent(self) -> 'd':
		return self.batt.current

	@dbus.method()
	async def SetCurrent(self, data: 'd') -> 'b':
		# update the scale appropriately
		await self.batt.set_current(data)
		return True

	@dbus.signal()
	async def CellVoltageChanged(self) -> 'a(db)':
		"""
		Send cell voltages and bypass flags
		"""
		return [(c.voltage,c.in_balance) for c in self.batt.cells]

	@dbus.signal()
	async def VoltageChanged(self) -> 'ddbb':
		"""
		Send pack voltage
		"""
		batt = self.batt
		return (batt.voltage,batt.current, batt.chg_set, batt.dis_set)

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
	voltage:float = None
	current:float = None
	power:float = None
	n_w:float = 0

	w_past:float = 0
	nw_past:float = 0

	vsum_warn:bool = False

	chg_set:bool = None
	dis_set:bool = None

	def __init__(self, ctrl, cfg, gcfg, start, num):
		self.name = cfg.name if "name" in cfg else "battery1"
		self.num = num
		if num is None:
			num = 0
		self.ctrl = ctrl
		self.path = f"/bms/{num}"
		self.ready = 0

		self.cfg = cfg
		self.gcfg = gcfg

		self.start = start
		self.end = start+self.cfg.n-1

		self.ready_evt = Event()

		self.cells = []
		for c in range(self.cfg.n):
			try:
				ccfg = cfg.cell.cells[c]
			except (AttributeError, IndexError):
				ccfg = attrdict()
			ccfg = combine_dict(ccfg, cfg.cell.default, cls=attrdict)
			cell = Cell(self, nr=self.start+c, path=f"/bms/{num}/{c}", cfg=ccfg, bcfg=self.cfg, gcfg=gcfg)
			self.ctrl.add_cell(cell)
			self.cells.append(cell)

	def __repr__(self):
		return f"‹Batt {self.path} u={'?' if self.voltage is None else self.voltage} i={'?' if self.current is None else self.current}›"

	@property
	def req(self):
		return self.ctrl.req

	@property
	def victron(self):
		return self.ctrl.victron

	@property
	def busname(self):
		return self.ctrl.busname

	@cached_property
	def cfg_path(self):
		return self.ctrl.cfgpath | "batteries" | self.batt.num

	async def run(self, evt):
		dbus = self.ctrl.dbus
		try:
			async with BatteryInterface(self, dbus) as intf:
				self._intf = intf

				await self._run(evt)
		finally:
			self._intf = None

	async def _run(self, evt):
		async with TaskGroup() as tg:
			await tg.spawn(self._read_update)

			h,res = await self.send(RequestGetSettings())
			if len(res) != len(self.cells):
				raise ConfigError(f"Battery {self.start}:{self.end}: found {len(res)} modules, not {len(self.cells)}")

			for c,r in zip(self.cells,res):
				r.to_cell(c)

			for c in self.cells:
				await tg.spawn(c.run)

			await tg.spawn(self.task_keepalive)
			await tg.spawn(self.task_voltage)
			await tg.spawn(self.task_cellvoltage)
			await tg.spawn(self.task_celltemperature)

			await self.ready_evt.wait()
			evt.set()


	async def task_keepalive(self):
		try:
			t = self.ctrl.cfg.poll.k / 2.1
		except AttributeError:
			return
		while True:
			await self.ctrl.req.send([self.ctrl.name,"live"])
			self.is_ready(0x01)

			await sleep_ms(t)

	def is_ready(self, val=None):
		if self.ready is None:
			return True
		if val is not None:
			self.ready |= val
		if self.ready == 0x0F:
			self.ready_evt.set()
			self.ready = None
			return True
		return False


	async def task_voltage(self):
		"""
		Periodically check the battery voltages
		"""
		gen = 0
		while True:
			res = await self.req.send([self.ctrl.name,"info"], gen=gen)
			gen = res.pop("gen", 0)
			self.update_global(**res)
			await self.check_limits()
			await self._intf.VoltageChanged()
			await self.victron.update_voltage()
			self.is_ready(0x08)

			await sleep(self.ctrl.cfg.t.voltage)


	async def task_cellvoltage(self):
		"""
		Periodically check the cell voltages
		"""
		while True:
			hdr,res = await self.send(RequestCellVoltage())
			chg = False
			for c,r in zip(self.cells,res):
				chg = r.to_cell(c) or chg
			if chg:
				await self.check_limits()
				await self._intf.CellVoltageChanged()
			self.is_ready(0x02)

			await self.victron.update_cells()

			await sleep(self.ctrl.cfg.t.cellvoltage)


	def get_soc(self):
		# this is the naïve way which doesn't work at all,
		# but there's no better way until we do an initial
		# charge-balance-discharge-charge cycle
		r = self.cfg.u.ext.max - self.cfg.u.ext.min
		return (self.voltage-self.cfg.u.ext.min)/r


	def get_cell_midvoltage(self):
		# returns (median, percentage_off)
		# The median is calculated by summing the voltages of the "low"
		# cells, rather than the midpoint voltage of the physical battery
		# (a) it's more expressive, (b) no guarantee that the cell order
		# reflects the physical battery layout
		v = [c.voltage for c in self.cells]
		v.sort()
		mp = len(v)//2
		v_l = sum(v[:mp])
		v_h = sum(v[mp:])
		if len(v) % 2:
			v_l += v[mp]/2
			v_h -= v[mp]/2
		return v_l, (1 - v_l/v_h)*100

	def get_cell_min_voltage(self):
		return min(c.voltage for c in self.cells)

	def get_cell_max_voltage(self):
		return max(c.voltage for c in self.cells)

	async def check_limits(self):
		"""
		Verify that the battery voltages are within spec.
		"""
		chg_ok = self.chg_set
		dis_ok = self.dis_set
		off = False


		if self.voltage is not None:
			try:
				vsum = sum(c.voltage for c in self.cells)
			except TypeError:
				pass
			else:
				if not self.vsum_warn and abs(vsum-self.voltage) > vsum*0.02:
					logger.warning("Voltage doesn't match: reported %.2f, sum %.2f", self.voltage, vsum)
					self.vsum_warn = True
				elif self.vsum_warn and abs(vsum-self.voltage) < vsum*0.015:
					logger.warning("Voltage matches again: reported %.2f, sum %.2f", self.voltage, vsum)
					self.vsum_warn = False

			if chg_ok and self.voltage >= self.cfg.u.ext.max:
				logger.warning("Voltage %.2f high, no charging", self.voltage)
				chg_ok = False
			elif not chg_ok and self.voltage < self.cfg.u.ext.max-0.05:
				if chg_ok is not None:
					logger.warning("Voltage %.2f no longer high, charging", self.voltage)
				chg_ok = True

			if self.voltage >= self.cfg.u.max:
				off = True
				logger.error("Overvoltage %.2f, turned off", self.voltage)

			if dis_ok and self.voltage <= self.cfg.u.ext.min:
				logger.warning("Voltage %.2f low, no discharging", self.voltage)
				dis_ok = False
			elif not dis_ok and self.voltage > self.cfg.u.ext.min+0.05:
				if dis_ok is not None:
					logger.warning("Voltage %.2f no longer low, discharging", self.voltage)
				dis_ok = True

			if self.voltage <= self.cfg.u.min:
				off = True
				logger.error("Undervoltage %.2f, turned off", self.voltage)

		if self.current is not None:
			pass  # XXX TODO check current limits here also

		for c in self.cells:
			if c.voltage is not None:
				if c.voltage >= c.cfg.u.ext.max:
					chg_ok = False
					logger.warning(f"{c} voltage high, no charging")

				if c.voltage >= c.cfg.u.max:
					logger.error(f"{c} overvoltage, turned off")

				if c.voltage <= c.cfg.u.ext.min:
					dis_ok = False
					logger.warning(f"{c} voltage low, no discharging")

				if c.voltage <= c.cfg.u.min:
					off = True
					logger.error(f"{c} undervoltage, turned off")

		if off and self.is_ready():
			await self.ctrl.req.send([self.ctrl.name,"rly"], st=False)

		if self.chg_set != chg_ok or self.dis_set != dis_ok:
			# send limits to BMS in mplex
			self.chg_set = chg_ok
			self.dis_set = dis_ok
			await self.victron.update_dc()


	async def task_celltemperature(self):
		"""
		Periodically check the cell temperatures
		"""
		while True:
			hdr,res = await self.send(RequestCellTemperature())
			chg = False
			for c,r in zip(self.cells,res):
				chg = r.to_cell(c) or chg
			if chg:
				await self._intf.CellTemperatureChanged()
				await self.victron.update_temperature()
			self.is_ready(0x04)

			await sleep(self.ctrl.cfg.t.celltemperature)


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
			await self.voltage(**msg)


	def update_global(self, u=None,i=None,w=None,**kw):
		if u is not None:
			self.voltage = u

		if i is not None:
			self.current = i

		if w is not None:
			s = w["s"]
			n = w["n"]
			if n < self.n_w:
				self.w_past += self.power
				self.nw_past += self.n_w
			self.power = s
			self.n_w = n

	async def set_voltage(self, val):
		# TODO move this to a config update handler
		adj = (val - self.cfg.u.offset) / (self.voltage - self.cfg.u.offset)
		self.cfg.u.scale *= adj
		if self.num is None:
			await self.ctrl.cmd.send(["sys","cfg"],
				cfg=attrdict()._update(("apps",self.ctrl.name,"cfg","batt","u"), {"scale":self.cfg.u.scale}))
		else:
			await self.ctrl.cmd.send(["sys","cfg"],
				cfg=attrdict()._update(("apps",self.ctrl.name,"cfg","batt",self.num,"u"), {"scale":self.cfg.u.scale}))

		self.voltage = val
		return True

	async def set_current(self, val):
		# TODO move this to a config update handler
		adj = (val - self.cfg.i.offset) / (self.current - self.cfg.i.offset)
		self.cfg.i.scale *= adj
		if self.num is None:
			await self.ctrl.cmd.send(["sys","cfg"],
				cfg=attrdict()._update(("apps",self.ctrl.name,"cfg","batt","i"), {"scale":self.cfg.i.scale}))
		else:
			await self.ctrl.cmd.send(["sys","cfg"],
				cfg=attrdict()._update(("apps",self.ctrl.name,"cfg","batt",self.num,"i"), {"scale":self.cfg.i.scale}))

		self.current = val
		return True

