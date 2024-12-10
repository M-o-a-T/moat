
from . import BaseAppCmd
from moat.compat import ticks_ms, ticks_diff, sleep_ms, ticks_add, Event, TaskGroup, Queue
from moat.util import Queue
import sys
import anyio

import logging
logger = logging.getLogger(__name__)

# Serial packet forwarder
# cfg:
# uart: N
# tx: PIN
# rx: PIN
# baud: 9600
# max:
#   len: N
#   idle: MSEC
# start: NUM
# 

class SerialCmd(BaseAppCmd):
	cons_warn = False
	def __init__(self, *a, **k):
		super().__init__(*a, **k)
		self.qr = Queue(99)
		self.qp = Queue(99)

	async def cmd_pkt(self, data):
		await self.send([self.name, "pkt"], data)

	async def cmd_raw(self, data):
		await self.send([self.name, "raw"], data)

	async def cmd_in_pkt(self, data):
		try:
			self.qp.put_nowait(data)
		except anyio.WouldBlock:
			logger.error("Serial packet %s: too many unprocessed packets", self.name)
			raise

	async def cmd_in_raw(self, data):
		try:
			self.qr.put_nowait(data)
		except anyio.WouldBlock:
			if not self.cons_warn:
				self.cons_warn = True
				logger.warning("Serial raw %s: console data overflow", self.name)
		else:
			self.cons_warn = False

	async def loc_pkt(self):
		# retrieve the next packet
		return await self.qp.get()

	async def loc_raw(self):
		# retrieve the next raw serial message
		return await self.qr.get()
