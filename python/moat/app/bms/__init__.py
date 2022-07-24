import asyncdbus.service as _dbus
from asyncdbus.message_bus import MessageBus, BusType

from moat.cmd import BaseCmd
from moat.compat import ticks_ms, ticks_diff, sleep_ms, ticks_add, Event, TaskGroup
from moat.util import Queue, to_attrdict, attrdict
import sys
import anyio
from victron.dbus import Dbus
from .. import BaseApp

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

class NoSuchCell(RuntimeError):
    pass

class SpuriousData(RuntimeError):
    pass

class MessageLost(RuntimeError):
    pass


class BattCmd(BaseCmd):
    def __init__(self, *a):
		# name cfg gcfg
        super().__init__(*a)
		self.ctrl = Controller(self, self.name, self.cfg, self.gcfg)


#	async def loc_data(self):
#		# return "global" BMS data
#		await self.batt.updated.wait()
#		return self.batt.data

	async def run(self):
		async with MessageBus(Bustype.SYSTEM).connect() as bus:
#			async with TaskGroup() as tg:
#				await tg.spawn(self.ctrl.run, bus)
			await self.ctrl.run(bus)



		self.batt.started.set()


