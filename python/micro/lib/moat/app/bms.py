
from moat.cmd import BaseCmd
from moat.compat import ticks_ms, ticks_diff, sleep_ms, ticks_add, Event
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

	def _check(self):
		c = self.cfg
		d = c["poll"]["d"]

		u = self.adc_u.read_u16() * self.cfg["u"]["scale"] + self.cfg["u"]["offset"]
		i = (self.adc_i.read_u16()-self.adc_ir.read_u16()) * self.cfg["i"]["scale"] + self.cfg["i"]["offset"]
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

	def update_cfg(self, cfg):
		ocfg = self.cfg
		self.cfg = cfg
		res = dict(
			w=self.sum_w,
			n=self.n_w,
		)
		self.sum_w = 0
		self.n_w = 0
		self.val_u = (self.val_u-ocfg['u']['offset'])/ocfg['u']['scale']*cfg['u']['scale']+cfg['u']['offset']
		self.val_i = (self.val_i-ocfg['i']['offset'])/ocfg['i']['scale']*cfg['i']['scale']+cfg['i']['offset']
		return res

	async def run(self):
		self.adc_u = M.ADC(M.Pin(self.cfg["u"]["pin"]))
		self.adc_i = M.ADC(M.Pin(self.cfg["i"]["pin"]))
		self.adc_ir = M.ADC(M.Pin(self.cfg["i"]["ref"]))
		self.relay = M.Pin(self.cfg["rel"]["pin"], M.Pin.OUT)
		self.sum_w = 0
		self.n_w = 0
		self.relay_force = None

		def sa(a,n=10):
			s=0
			for _ in range(n):
				s += a.read_u16()
			return s/n
		self.val_u = sa(self.adc_u) * self.cfg["u"]["scale"] + self.cfg["u"]["offset"]
		self.val_i = (sa(self.adc_i)-sa(self.adc_ir)) * self.cfg["i"]["scale"] + self.cfg["i"]["offset"]

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
				if self.sw_ok and self.relay_force is None and not self.relay.value():
					self.relay.on()
					await self.send_rly_state()

					xmit_n=0

			elif self.relay_force is None and self.relay.value():
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
		await self.request.send_nr([self.name,"relay"],
				{"state": self.relay.value(), "force": self.relay_force})


class BattCmd(BaseCmd):
	def __init__(self, parent, batt, name):
		super().__init__(parent)
		self.batt = batt
		self.name = name

	def run(self):
		while True:
			await self.batt.xmit_evt.wait()
			await self.request.send_nr([self.name,"info"], self.batt.stat())
	
	async def cmd_rly(self, st):
		await self.batt.set_relay_force(st)

	def cmd_s(self):
		return self.batt.stat()

	def cmd_cfg(self, cfg=None):
		if cfg is None:
			return self.batt.cfg
		res = self.batt.update_cfg(cfg)
		await self.request.send_nr([self.name,"cfg"], cfg=self.batt.cfg)
		return res
