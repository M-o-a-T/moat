
from moat.cmd import BaseCmd
from moat.compat import ticks_ms, ticks_diff, sleep_ms, ticks_add, Event, TaskGroup, Queue
from moat.util import Queue, to_attrdict
import sys
import anyio

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

class Serial:
	def __init__(self, cfg, gcfg, name):
		self.cfg = cfg
		self.gcfg = gcfg
		self.name = name
		self.qr = Queue(10)
		self.qp = Queue(10)

class SerialCmd(BaseCmd):
	def __init__(self, parent, ser, name):
		super().__init__(parent)
		self.ser = ser
		self.name = name

	async def cmd_pkt(self, data):
		await self.send([self.name, "pkt"], data)

	async def cmd_raw(self, data):
		await self.send([self.name, "raw"], data)

	async def cmd_pkt(self, data):
		logger.info("DATA %s", data)
		self.ser.qp.put_nowait(data)

	async def cmd_in_raw(self, data):
		logger.info("CONS %s", data)
		self.ser.qr.put_nowait(data)

	async def cmd_in_pkt(self, data):
		logger.info("DATA %s", data)
		self.ser.qp.put_nowait(data)

	async def loc_pkt(self):
		# retrieve the next packet
		return await self.ser.qp.get()

	async def loc_raw(self):
		# retrieve the next raw serial message
		return await self.ser.qr.get()
