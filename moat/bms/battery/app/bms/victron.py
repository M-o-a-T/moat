import asyncdbus.service as _dbus
from moat.cmd import BaseCmd
from moat.compat import ticks_ms, ticks_diff, sleep_ms, ticks_add, Event, TaskGroup
from moat.util import Queue, attrdict
import sys
import anyio
from victron.dbus import Dbus

import logging
logger = logging.getLogger(__name__)

# cfg:
#   batt:
# u:
#   pin: PIN  # measure U
#   min: VAL
#   max: VAL
# i:
#   pin: PIN  # measure I
#   ref: PIN  # I reference, subtract from measurement
#   min: VAL
#   max: VAL
# poll:
#   t: MSEC
#   d: FACTOR # decay, for averaging, 1000/th
# rel: PIN  # relay
# 

class BatteryState:
	cell_okchg = None
	cell_okdis = None
	data = None
	u=None
	i=None
	ctrl = None

	def __init__(self, ctrl):
		super().__init__()
		self.ctrl = ctrl
		self.q = Queue(2)
		self.started = Event()
		self.updated = Event()

	async def config_updated(self):
		cfg = self.ctrl.batt[0].cfg
		u_min = cfg.u.ext.min
		u_max = cfg.u.ext.max
		i_min = cfg.i.ext.min
		i_max = cfg.i.ext.max

		for b in self.ctrl.batt[1:]:
			c = b.cfg
			u_min = max(u_min,c.u.ext.min)
			u_max = min(u_max,c.u.ext.max)
			i_min += c.i.ext.min
			i_max += c.i.ext.max
			# This blithedly assumes that the internal resistances of all
			# batteries are identical, which most probably is wrong.
			# TODO measure current spread at suitable power points, reduce
			# the result accordingly.

		async with self._srv as l:
			await l.set(self.bus.vlo, float(u_min))
			await l.set(self.bus.vhi, float(u_max))
			await l.set(self.bus.ich, -float(i_min))
			await l.set(self.bus.idis, float(i_max))


	async def update_dc(self):
		# update charge and discharge flags
		chg_ok = all(b.chg_set for b in self.ctrl.batt)
		dis_ok = all(b.dis_set for b in self.ctrl.batt)

		async with self._srv as l:
			await l.set(self.bus.okchg, chg_ok)
			await l.set(self.bus.okdis, dis_ok)


	async def update_cells(self):
		async with self.srv as l:
			mv,mvd = self.ctrl.batt[0].get_cell_midvoltage()
			await l.set(self.bus.mv0, mv)
			await l.set(self.bus.mvd0, mvd)
		

	async def update_voltage(self):
		ok = False
		try:
			u = sum(b.voltage for b in self.ctrl.batt) / len(self.ctrl.batt)
			i = sum(b.current for b in self.ctrl.batt)
			ok = True
		except ValueError:
			u = i = None

		async with self.srv as l:
			await l.set(self.bus.sta, 9 if ok else 10)
			await l.set(self.bus.err, 0 if ok else 12)
			await l.set(self.bus.v0, u)
			await l.set(self.bus.c0, i)
			await l.set(self.bus.p0, u*i if u is not None else None)

	@property
	def name(self):
		return self.ctrl.name

	@property
	def srv(self):
		return self._srv

	async def run(self, evt=None):
		name = "com.victronenergy.battery."+self.name
		async with Dbus() as bus, bus.service(name) as srv:
			logger.debug("Setting up")
			self._bus = bus
			self.bus = attrdict()
			self._srv = srv

			await srv.add_mandatory_paths(
				processname=__file__,
				processversion="0.1",
				connection='MoaT '+self.ctrl.gcfg.port.dev,
				deviceinstance=1,
				productid=1,
				productname="MoaT BMS",
				firmwareversion="0.1",
				hardwareversion=None,
				connected=1,
			)

			self.bus.vlo = await srv.add_path("/Info/BatteryLowVoltage", None,
						gettextcallback=lambda p, v: "{:0.2f} V".format(v))
			self.bus.vhi = await srv.add_path("/Info/MaxChargeVoltage", None,
						gettextcallback=lambda p, v: "{:0.2f} V".format(v))
			self.bus.ich = await srv.add_path("/Info/MaxChargeCurrent", None,
						gettextcallback=lambda p, v: "{:0.2f} A".format(v))
			self.bus.idis = await srv.add_path("/Info/MaxDischargeCurrent", None,
						gettextcallback=lambda p, v: "{:0.2f} A".format(v))

			self.bus.sta = await srv.add_path("/State",1)
			self.bus.err = await srv.add_path("/Error",0)
			self.bus.ncell = await srv.add_path("/System/NrOfCellsPerBattery",8)
			self.bus.non = await srv.add_path("/System/NrOfModulesOnline",1)
			self.bus.noff = await srv.add_path("/System/NrOfModulesOffline",0)
			self.bus.nbc = await srv.add_path("/System/NrOfModulesBlockingCharge",None)
			self.bus.nbd = await srv.add_path("/System/NrOfModulesBlockingDischarge",None)
			self.bus.cap = await srv.add_path("/Capacity", 4.0)
			self.bus.capi = await srv.add_path("/InstalledCapacity", 5.0)
			self.bus.cons = await srv.add_path("/ConsumedAmphours", 12.3)

			self.bus.soc = await srv.add_path('/Soc', 30)
			self.bus.soh = await srv.add_path('/Soh', 90)
			self.bus.v0 = await srv.add_path('/Dc/0/Voltage', None,
						gettextcallback=lambda p, v: "{:2.2f}V".format(v))
			self.bus.c0 = await srv.add_path('/Dc/0/Current', None,
						gettextcallback=lambda p, v: "{:2.2f}A".format(v))
			self.bus.p0 = await srv.add_path('/Dc/0/Power', None,
						gettextcallback=lambda p, v: "{:0.0f}W".format(v))
			self.bus.t0 = await srv.add_path('/Dc/0/Temperature', 21.0)
			self.bus.mv0 = await srv.add_path('/Dc/0/MidVoltage', None,
						gettextcallback=lambda p, v: "{:0.2f}V".format(v))
			self.bus.mvd0 = await srv.add_path('/Dc/0/MidVoltageDeviation', None,
						gettextcallback=lambda p, v: "{:0.1f}%".format(v))

			# battery extras
			self.bus.minct = await srv.add_path('/System/MinCellTemperature', None)
			self.bus.maxct = await srv.add_path('/System/MaxCellTemperature', None)
			self.bus.maxcv = await srv.add_path('/System/MaxCellVoltage', None,
						gettextcallback=lambda p, v: "{:0.3f}V".format(v))
			self.bus.maxcvi = await srv.add_path('/System/MaxVoltageCellId', None)
			self.bus.mincv = await srv.add_path('/System/MinCellVoltage', None,
						gettextcallback=lambda p, v: "{:0.3f}V".format(v))
			self.bus.mincvi = await srv.add_path('/System/MinVoltageCellId', None)
			self.bus.hcycles = await srv.add_path('/History/ChargeCycles', None)
			self.bus.htotalah = await srv.add_path('/History/TotalAhDrawn', None)
			self.bus.bal = await srv.add_path('/Balancing', None)
			self.bus.okchg = await srv.add_path('/Io/AllowToCharge', 0)
			self.bus.okdis = await srv.add_path('/Io/AllowToDischarge', 0)
			# xx = await srv.add_path('/SystemSwitch',1)

			# alarms
			self.bus.allv = await srv.add_path('/Alarms/LowVoltage', None)
			self.bus.alhv = await srv.add_path('/Alarms/HighVoltage', None)
			self.bus.allc = await srv.add_path('/Alarms/LowCellVoltage', None)
			self.bus.alhc = await srv.add_path('/Alarms/HighCellVoltage', None)
			self.bus.allow = await srv.add_path('/Alarms/LowSoc', None)
			self.bus.alhch = await srv.add_path('/Alarms/HighChargeCurrent', None)
			self.bus.alhdis = await srv.add_path('/Alarms/HighDischargeCurrent', None)
			self.bus.albal = await srv.add_path('/Alarms/CellImbalance', None)
			self.bus.alfail = await srv.add_path('/Alarms/InternalFailure', None)
			self.bus.alhct = await srv.add_path('/Alarms/HighChargeTemperature', None)
			self.bus.allct = await srv.add_path('/Alarms/LowChargeTemperature', None)
			self.bus.alht = await srv.add_path('/Alarms/HighTemperature', None)
			self.bus.allt = await srv.add_path('/Alarms/LowTemperature', None)

			if evt is not None:
				evt.set()
			while True:
				await anyio.sleep(99999)
