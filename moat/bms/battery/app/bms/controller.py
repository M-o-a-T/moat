#
import asyncdbus.service as _dbus
from asyncdbus.signature import Variant
from asyncdbus.constants import NameFlag
from pprint import pformat
from functools import cached_property
from contextlib import asynccontextmanager

from moat.compat import CancelledError, sleep, sleep_ms, wait_for_ms, ticks_ms, ticks_diff, ticks_add, TimeoutError, Lock, TaskGroup
from moat.util import ValueEvent, combine_dict, attrdict, Ctx
from moat.dbus import DbusInterface

from .cell import Cell
from .packet import *

import logging
logger = logging.getLogger(__name__)


class ControllerInterface(DbusInterface):
    def __init__(self, ctrl, dbus):
        self.ctrl = ctrl
        super().__init__(dbus, "/BMS", "bms")

    def done(self):
        del self.ctrl
        super().done()

	@_dbus.method()
	async def GetNBatteries(self) -> 'y':
		"""
		Number of batteries on this controller
		"""
		return len(self.ctrl.batt)


class Controller:
	"""
	Main controller for our BMS.

	TODO support more than one battery
	"""
	def __init__(self, name, cmd, cfg, gcfg):
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
		self.baud = gcfg.apps[cfg.serial].cfg.baud
		self.waiting = [None]*8

		n = 0
		for i,b in enumerate(cfg.batteries):
			batt = Battery(self, b, gcfg, n,i)
			self.batt.append(batt)
			n += b.n

	def add_cell(self, cell):
		self.cells.append(cell)

	def cfg_name(self):
		return self.name

	@cached_property
	def cfg_path(self):
		return Path("bms", self.name)

	async def run(self, dbus):
		self._dbus = dbus
        try:
            async with DbusName(dbus, f"+bms.{self.name}"), ControllerInterface(self, dbus) as intf:
                self._intf = intf
                await self._run()
        finally:
			intf.done()
            del self.cmd
            del self._dbus
            del self._intf

	@property
	def dbus(self):
		return self._dbus

	@property
	def req(self):
		return self._req

	@property
	def intf(self):
		return self._intf


	async def _run(self):
		async with TaskGroup() as tg:
			await tg.spawn(self._read)
			for b in self.batt:
				await tg.spawn(b.run, self._req, self._dbus)


	async def send(self, *a,**k):
		"""
		Send a message to the cells.
		Returns the per-battery replies.

		Retries a few times before erroring out.
		"""

		err = None
		for n in range(5):
			try:
				return await self._send(*a,**k)
			except (TimeoutError,MessageLost) as e:
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

		if not isinstance(pkt,(list,tuple)):
			pkt = (pkt,)
		h = PacketHeader(command=pkt[0].T, start=start or 0, broadcast=broadcast)
		for p in pkt[1:]:
			if p.T != h.command:
				raise ValueError("Needs same type, not %s vs %s", pkt[0], p)

		if start is None or broadcast:
			if len(pkt) != 1 or not broadcast:
				raise RuntimeError("Broadcast means one message")
			h.cells = MAXCELLS-1
		elif end is not None:
			h.cells = end-start
			if pkt[0].S.size > 0 and len(pkt) != h.cells+1:
				raise ValueError("Wrong packet count, %d vs %d for %s" % (len(pkt), h.cells+1, pkt[0]))
		else:
			h.cells = len(pkt)-1
		msg = b"".join(p.to_bytes() for p in pkt)

		async with self.w_lock:
			t = ticks_ms()
			td = ticks_diff(self.t,t)
			if td > 0:
				await sleep_ms(td)

			h.sequence = seq = self.seq
			self.seq = (self.seq + 1) % 8
			evt = self.waiting[seq]
			if evt is not None:
				# wait for prev request to complete
				await evt.wait()
			self.waiting[seq] = evt = ValueEvent()

			# We need to delay by whatever the affected cells add to the
			# message, otherwise the next msg might catch up
			msg = h.to_bytes()+msg
			n_cells = h.cells+1
			mlen = len(msg) + n_cells*(replyClass[h.command].S.size+h.S.size+4)

			self.t = t + 10000*mlen/self.baud
			await self.req.send([self.cfg.serial, "send"], data=msg)

		res = await wait_for_ms(5000, evt.get)
		logger.debug("REQ %s",pkt)
		logger.debug("RES %s",pformat(res))
		return res

	async def _read(self):
		# task to read serial data from the Serial subsystem
		def set_err(seq, err):
			n,self.waiting[seq] = self.waiting[seq],None
			if n is not None:
				n.set_error(err)

		xseq = 0
		while True:
			msg = await self.cmd.send(["local",self.cfg.serial,"pkt"])
			# TODO set up a subscription mechanism

			off = PacketHeader.S.size
			hdr = PacketHeader.from_bytes(msg[0:off])
			while xseq != hdr.sequence:
				set_err(xseq, MessageLost())
				xseq = (xseq+1) & 0x07
			if not hdr.seen:
				set_err(hdr.sequence, NoSuchCell(hdr.start))
				continue
			RC = replyClass[hdr.command]
			RCL = RC.S.size
			pkt = []
			if hdr.broadcast:
				# The request header has not been deleted,
				# so we need to skip it
				off += RC.S.size
			if RCL:
				while off < len(msg):
					if off+RCL > len(msg):
						break  # incomplete
					pkt.append(RC.from_bytes(msg[off:off+RCL]))
					off += RCL
			if off != len(msg):
				set_err(hdr.sequence, SpuriousData(msg))
				continue

			evt, self.waiting[hdr.sequence] = self.waiting[hdr.sequence], None
			if evt is not None:
				evt.set((hdr,pkt))

