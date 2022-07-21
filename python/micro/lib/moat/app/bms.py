
from moat.cmd import BaseCmd
from moat.compat import ticks_ms, ticks_diff, sleep_ms, wait_for_ms, ticks_add, Event, TimeoutError
import machine as M

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
	def __init__(self, cfg, gcfg):
		self.cfg = cfg
		self.xmit_evt = Event()
		self.cmd = None

	def _check(self):
		c = self.cfg
		d = c["poll"]["d"]

		u = self.adc_u.read_u16() * self.adc_u_scale + self.adc_u_offset
		i = (self.adc_i.read_u16()-self.adc_ir.read_u16()) * self.adc_i_scale + self.adc_i_offset
		self.val_u = (self.val_u*(1000-d) + u*d) / 1000
		self.val_i = (self.val_i*(1000-d) + i*d) / 1000

		self.sum_w += self.val_u*self.val_i
		self.n_w += 1

		if self.val_u < c["u"]["min"]:
			return False
		if self.val_u > c["u"]["max"]:
			return False
		if self.val_i < c["i"]["min"]:
			return False
		if self.val_i > c["i"]["max"]:
			return False
		return True

	def stat(self):
		res = dict(
			ok=self.relay.value(),
			u=self.val_u,
			i=self.val_i,
			w=self.sum_w,
			n=self.n_w,
		)
		return res

	async def set_relay_force(self, st):
		self.relay_force = st
		if st is not None:
			self.relay.value(st)
			await self.send_rly_state()
		else:
			self.sw_ok = False

	def live_state(self, live:bool):
		if self.live == live:
			return
		self.live = live
		if not live:
			self.relay.off()

	def set_live(self):
		self.live_flag.set()
	
	async def live_task(self):
		while True:
			try:
				await wait_for_ms(self.cfg.poll.k, self.live_flag.wait)
			except TimeoutError:
				self.live_state(False)
			else:
				self.live_flag = Event()
				self.live_state(True)

	def config_updated(self):
		old_u_scale, old_u_offset = self.adc_u_scale, self.adc_u_offset
		old_i_scale, old_i_offset = self.adc_i_scale, self.adc_i_offset
		self._set_scales()
		self.val_u = (self.val_u-old_u_offset)/old_u_scale*self.adc_u_scale+self.adc_u_offset
		self.val_i = (self.val_i-old_i_offset)/old_i_scale*self.adc_i_scale+self.adc_i_offset

		res = dict(
			w=self.sum_w,
			n=self.n_w,
		)
		self.sum_w = 0
		self.n_w = 0
		return res

	def _set_scales(self):
		self.adc_u_scale = self.cfg["u"]["scale"]
		self.adc_u_offset = self.cfg["u"]["offset"]
		self.adc_i_scale = self.cfg["i"]["scale"]
		self.adc_i_offset = self.cfg["i"]["offset"]

	async def run(self):
		self.adc_u = M.ADC(M.Pin(self.cfg["u"]["pin"]))
		self.adc_i = M.ADC(M.Pin(self.cfg["i"]["pin"]))
		self.adc_ir = M.ADC(M.Pin(self.cfg["i"]["ref"]))
		self.relay = M.Pin(self.cfg["rel"]["pin"], M.Pin.OUT)
		self.sum_w = 0
		self.n_w = 0
		self.relay_force = None
		self.live = self.relay.value()
		self.live_flag = Event()
		# we start off with the current relay state
		# so a soft reboot won't toggle the relay

		self._set_scales()

		def sa(a,n=10):
			s=0
			for _ in range(n):
				s += a.read_u16()
			return s/n
		self.val_u = sa(self.adc_u) * self.adc_u_scale + self.adc_u_offset
		self.val_i = (sa(self.adc_i)-sa(self.adc_ir)) * self.adc_i_scale + self.adc_i_offset

		self.sw_ok = False

		self.t = ticks_ms()
		self.t_sw = ticks_add(ticks_ms(), self.cfg["rel"]["t1"])
		xmit_n = 0

		while True:
			self.t = ticks_add(self.t, self.cfg["poll"]["t"])

			if not self.sw_ok:
				if ticks_diff(self.t,self.t_sw) > 0:
					self.sw_ok = True
					xmit_n=0

			if self._check():
				if self.sw_ok and self.live and self.relay_force is None and not self.relay.value():
					self.relay.on()
					await self.send_rly_state()

					xmit_n=0

			elif self.live and self.relay_force is None and self.relay.value():
				self.relay.off()
				await self.send_rly_state()
				self.t_sw = ticks_add(self.t, self.cfg["rel"]["t"])
				self.sw_ok = False
				xmit_n=0

			xmit_n -= 1
			if xmit_n <= 0:
				self.xmit_evt.set()
				self.xmit_evt = Event()
				xmit_n = self.cfg["poll"]["n"]

			t = ticks_ms()
			td = ticks_diff(self.t, t)
			if td > 0:
				await sleep_ms(td)

	async def send_rly_state(self):
		if self.cmd is not None:
			await self.cmd.request.send_nr([self.cmd.name,"relay"],
				{"state": self.relay.value(), "force": self.relay_force, "live": self.live})


class BattCmd(BaseCmd):
	def __init__(self, parent, batt, name):
		super().__init__(parent)
		self.batt = batt
		batt.cmd = self
		self.name = name

	def run(self):
		while True:
			await self.batt.xmit_evt.wait()
			await self.request.send_nr([self.name,"info"], self.batt.stat())
	
	async def config_updated(self):
		await super().config_updated()
		res = self.batt.config_updated()
		await self.request.send_nr([self.name,"work"], work=res, final=True)

	async def cmd_rly(self, st):
		"""
		Called manually, but also irreversibly when there's a "hard" cell over/undervoltage
		"""
		await self.batt.set_relay_force(st)

	def cmd_stat(self):
		return self.batt.stat()

	def cmd_live(self):
		self.batt.set_live()

