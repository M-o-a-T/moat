import asyncdbus.service as _dbus
from moat.cmd import BaseCmd
from moat.compat import ticks_ms, ticks_diff, sleep_ms, ticks_add, Event, TaskGroup
from moat.util import Queue, to_attrdict, attrdict
import sys
import anyio
from victron.dbus import Dbus

import logging
logger = logging.getLogger(__name__)

# cfg:
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

class Batt(_dbus.ServiceInterface):
	cell_okch = None
	cell_okdis = None
	data = None
	u=None
	i=None
	ctrl = None

	def __init__(self, cfg, gcfg, name):
		super().__init__("org.m_o_a_t.bms")
		self.cfg = cfg
		self.gcfg = gcfg
		self.q = Queue(2)
		self.started = Event()
		self.updated = Event()
		self.__name = name

	async def set_cfg(self, cfg):
		# convert to attrdict
		self.cfg = cfg = to_attrdict(cfg)

		async with self._srv as l:
			await l.set(self.bus.vlo, float(cfg.u.ext.min))
			await l.set(self.bus.vhi, float(cfg.u.ext.max))
			await l.set(self.bus.ich, -float(cfg.i.ext.min))
			await l.set(self.bus.idis, float(cfg.i.ext.max))

	@property
	def srv(self):
		return self._srv

	async def _cfg_xmit(self):
		await anyio.sleep(1)
		while True:
			await self.set_cfg(self.cfg)
			await anyio.sleep(100)

	async def run(self, *, task_status=None):
		try:
			name = self.cfg.dbus
		except AttributeError:
			name = "com.victronenergy.battery."+self.__name
		async with Dbus() as bus, bus.service(name) as srv:
			print("Setting up")
			self._bus = bus
			self.bus = attrdict()
			self._srv = srv

			try:
				await bus.bus.export("/BMS", self)
				await self._run(task_status)
			finally:
				if bus.bus is not None:
					await bus.bus.unexport("/BMS", self)


	async def _run(self, task_status):
		if True: # TODO indent mask
			bus = self._bus
			srv = self._srv

			await srv.add_mandatory_paths(
				processname=__file__,
				processversion="0.1",
				connection='MoaT '+self.gcfg.port.dev,
				deviceinstance=1,
				productid=1,
				productname="MoaT BMS",
				firmwareversion="0.1",
				hardwareversion=None,
				connected=1,
			)

			self.bus.vlo = await srv.add_path("/Info/BatteryLowVoltage", None,
					   gettextcallback=lambda p, v: "{:0.2f}V".format(v))
			self.bus.vhi = await srv.add_path("/Info/MaxChargeVoltage", None,
					   gettextcallback=lambda p, v: "{:0.2f}V".format(v))
			self.bus.ich = await srv.add_path("/Info/MaxChargeCurrent", None,
					   gettextcallback=lambda p, v: "{:0.2f}A".format(v))
			self.bus.idis = await srv.add_path("/Info/MaxDischargeCurrent", None,
					   gettextcallback=lambda p, v: "{:0.2f}A".format(v))

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
			self.bus.okch = await srv.add_path('/Io/AllowToCharge', 0)
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

			# This is not true strictly speaking but we need the command to proceed
			if task_status is not None:
				task_status.started()

			await self.started.wait()
			await srv.setup_done()
			print("Started")

			async with TaskGroup() as tg:
				await tg.spawn(self._cfg_xmit)

				async for msg in self.q:
					u=msg["u"]
					i=msg["i"]
					w=msg["w"]
					ok=msg["ok"]

					self.u = u
					self.i = i
					async with srv as l:
						await l.set(self.bus.sta, 9 if ok else 10)
						await l.set(self.bus.err, 0 if ok else 12)
						await l.set(self.bus.v0, u)
						await l.set(self.bus.c0, i)
						await l.set(self.bus.p0, u*i)
						await l.set(self.bus.okch, self.cell_okch and u < self.cfg.u.ext.max*0.98)
						await l.set(self.bus.okdis, self.cell_okdis and u > self.cfg.u.ext.min*1.02)

					# internal forwarding
					self.data = msg
					self.updated.set()
					self.updated = Event()

	@_dbus.method()
	async def SetVoltage(self, data: 'd') -> 'b':
		# update the scale appropriately
		adj = (data - self.cfg.u.offset) / (self.u - self.cfg.u.offset)
		self.cfg.u.scale *= adj
		await self.ctrl.send(["sys","cfg"], cfg=attrdict()._update(("app",self.__name,"cfg","u"), {"scale":self.cfg.u.scale})) 

		# TODO move this to a config update handler
		self.u = data
		return True


	async def add_energy(self, data, final=False):
		from pprint import pformat
		print("AE",final,pformat(data))
		pass

	async def set_cell_ok(self, okch,okdis):
		async with self._srv as l:
			self.cell_okch = okch
			self.cell_okdis = okdis
			await l.set(self.bus.okch, self.cell_okch and self.u is not None and self.u < self.cfg.u.ext.max*0.99 and self.i > self.cfg.i.ext.min*0.98)
			await l.set(self.bus.okdis, self.cell_okdis and self.u is not None and self.u > self.cfg.u.ext.min*1.01 and self.i < self.cfg.i.ext.max*0.98)

class BattCmd(BaseCmd):
	def __init__(self, parent, batt, name):
		super().__init__(parent)
		self.batt = batt
		self.name = name
		batt.ctrl = self

	async def loc_set(self, **kw):
		# additional data to send to the bus
		async with self.batt.srv as l:
			for k,v in kw.items():
				await l.set(self.bus[k], v)

	async def loc_cell(self, okch, okdis):
		# Cell voltages in range?
		await self.batt.set_cell_ok(okch,okdis)

	async def loc_data(self):
		# return "global" BMS data
		await self.batt.updated.wait()
		return self.batt.data

	async def run(self):
		if self.batt.cfg:
			# send to remote
			res = await self.send(["sys","cfg"])
			res = res["apps"][self.name]
			await self.batt.add_energy(res, True)
		else:
			# load from remote
			self.batt.cfg = await self.send([self.name,"cfg"])
		self.batt.started.set()

	async def cmd_info(self, **kw):
		from pprint import pformat
		logger.info("DATA %s",pformat(kw))
		await self.batt.q.put(kw)

	async def cmd_relay(self, **kw):
		from pprint import pformat
		logger.info("RELAY %s",pformat(kw))

	async def cmd_work(self, **kw):
		from pprint import pformat
		logger.info("WORK %s",pformat(kw))

