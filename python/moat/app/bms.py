
from moat.cmd import BaseCmd
from moat.compat import ticks_ms, ticks_diff, sleep_ms, ticks_add, Event, TaskGroup
from moat.util import Queue, to_attrdict
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

class Batt:
	def __init__(self, cfg, gcfg, name):
		self.cfg = cfg
		self.gcfg = gcfg
		self.q = Queue(2)
		self.started = Event()
		self.name = name

	async def set_cfg(self, cfg):
		# convert to attrdict
		self.cfg = cfg = to_attrdict(cfg)

		async with self._srv as l:
			await l.set(self.vlo, float(cfg.u.ext.min))
			await l.set(self.vhi, float(cfg.u.ext.max))
			await l.set(self.ich, float(cfg.i.ext.min))
			await l.set(self.idis, float(cfg.i.ext.max))

	async def _cfg_xmit(self):
		await anyio.sleep(1)
		while True:
			await self.set_cfg(self.cfg)
			await anyio.sleep(100)

	async def run(self, *, task_status=None):
		async with Dbus() as bus, bus.service("com.victronenergy.battery."+self.name) as srv:
			print("Setting up")
			self._srv = srv
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

			self.vlo = await srv.add_path("/Info/BatteryLowVoltage", None,
					   gettextcallback=lambda p, v: "{:0.2f}V".format(v))
			self.vhi = await srv.add_path("/Info/MaxChargeVoltage", None,
					   gettextcallback=lambda p, v: "{:0.2f}V".format(v))
			self.ich = await srv.add_path("/Info/MaxChargeCurrent", None,
					   gettextcallback=lambda p, v: "{:0.2f}A".format(v))
			self.idis = await srv.add_path("/Info/MaxDischargeCurrent", None,
					   gettextcallback=lambda p, v: "{:0.2f}A".format(v))

			ncell = await srv.add_path("/System/NrOfCellsPerBattery",8)
			non = await srv.add_path("/System/NrOfModulesOnline",1)
			noff = await srv.add_path("/System/NrOfModulesOffline",0)
			nbc = await srv.add_path("/System/NrOfModulesBlockingCharge",None)
			nbd = await srv.add_path("/System/NrOfModulesBlockingDischarge",None)
			cap = await srv.add_path("/Capacity", 4.0)
			cap = await srv.add_path("/InstalledCapacity", 5.0)
			cap = await srv.add_path("/ConsumedAmphours", 12.3)

			soc = await srv.add_path('/Soc', 30)
			soh = await srv.add_path('/Soh', 90)
			v0 = await srv.add_path('/Dc/0/Voltage', None,
						gettextcallback=lambda p, v: "{:2.2f}V".format(v))
			c0 = await srv.add_path('/Dc/0/Current', None,
						gettextcallback=lambda p, v: "{:2.2f}A".format(v))
			p0 = await srv.add_path('/Dc/0/Power', None,
						gettextcallback=lambda p, v: "{:0.0f}W".format(v))
			t0 = await srv.add_path('/Dc/0/Temperature', 21.0)
			mv0 = await srv.add_path('/Dc/0/MidVoltage', None,
					   gettextcallback=lambda p, v: "{:0.2f}V".format(v))
			mvd0 = await srv.add_path('/Dc/0/MidVoltageDeviation', None,
					   gettextcallback=lambda p, v: "{:0.1f}%".format(v))

			# battery extras
			minct = await srv.add_path('/System/MinCellTemperature', None)
			maxct = await srv.add_path('/System/MaxCellTemperature', None)
			maxcv = await srv.add_path('/System/MaxCellVoltage', None,
					   gettextcallback=lambda p, v: "{:0.3f}V".format(v))
			maxcvi = await srv.add_path('/System/MaxVoltageCellId', None)
			mincv = await srv.add_path('/System/MinCellVoltage', None,
					   gettextcallback=lambda p, v: "{:0.3f}V".format(v))
			mincvi = await srv.add_path('/System/MinVoltageCellId', None)
			hcycles = await srv.add_path('/History/ChargeCycles', None)
			htotalah = await srv.add_path('/History/TotalAhDrawn', None)
			bal = await srv.add_path('/Balancing', None)
			okch = await srv.add_path('/Io/AllowToCharge', 0)
			okdis = await srv.add_path('/Io/AllowToDischarge', 0)
			# xx = await srv.add_path('/SystemSwitch',1)

			# alarms
			allv = await srv.add_path('/Alarms/LowVoltage', None)
			alhv = await srv.add_path('/Alarms/HighVoltage', None)
			allc = await srv.add_path('/Alarms/LowCellVoltage', None)
			alhc = await srv.add_path('/Alarms/HighCellVoltage', None)
			allow = await srv.add_path('/Alarms/LowSoc', None)
			alhch = await srv.add_path('/Alarms/HighChargeCurrent', None)
			alhdis = await srv.add_path('/Alarms/HighDischargeCurrent', None)
			albal = await srv.add_path('/Alarms/CellImbalance', None)
			alfail = await srv.add_path('/Alarms/InternalFailure', None)
			alhct = await srv.add_path('/Alarms/HighChargeTemperature', None)
			allct = await srv.add_path('/Alarms/LowChargeTemperature', None)
			alht = await srv.add_path('/Alarms/HighTemperature', None)
			allt = await srv.add_path('/Alarms/LowTemperature', None)

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
					async with srv as l:
						await l.set(v0, u)
						await l.set(c0, i)
						await l.set(p0, u*i)
						await l.set(okch, u < self.cfg.u.ext.max*0.99)
						await l.set(okdis, u > self.cfg.u.ext.min*1.01)
						# TODO
						# calculate SoC from self.total_w+w


	async def add_energy(self, data, final=False):
		from pprint import pformat
		print("AE",final,pformat(data))
		pass

class BattCmd(BaseCmd):
	def __init__(self, parent, batt, name):
		super().__init__(parent)
		self.batt = batt
		self.name = name

	async def run(self):
		if self.batt.cfg:
			# send to remote
			res = await self.send([self.name,"cfg"], cfg=self.batt.cfg)
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

	async def cmd_cfg(self, cfg):
		from pprint import pformat
		logger.info("NCFG %s",pformat(cfg))
		await self.batt.set_cfg(cfg)

