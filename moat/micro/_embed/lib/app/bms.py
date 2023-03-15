import sys

import machine as M
from moat.util import NotGiven

from moat.micro.cmd import BaseCmd
from moat.micro.compat import (
    Event,
    TaskGroup,
    TimeoutError,
    sleep_ms,
    ticks_add,
    ticks_diff,
    ticks_ms,
    wait_for_ms,
)


# see
#
class BMS:
    cmd = None

    def __init__(self, cfg, gcfg):
        self.cfg = cfg
        self.xmit_evt = Event()
        self.gen = 0  # generation, incremented every time a new value is read

    async def _check(self):
        c = self.cfg
        cc = c["batt"]
        d = c["poll"]["d"]

        u = 0
        i = 0
        ir = 0
        N = 2 * self.cfg["poll"]["n"]
        for _ in range(N):
            u += self.adc_u.read_u16()
            await sleep_ms(1)
            i += self.adc_i.read_u16()
            await sleep_ms(1)
            ir += self.adc_ir.read_u16()
            await sleep_ms(1)
        u = u / N * self.adc_u_scale + self.adc_u_offset
        i = (i - ir) / N * self.adc_i_scale + self.adc_i_offset
        self.val_u = u
        self.val_i = i

        self.sum_w += self.val_u * self.val_i
        self.n_w += 1

        if self.val_u < cc["u"]["min"]:
            if self.relay.value():
                print("UL", self.val_u, file=sys.stderr)
            return False
        if self.val_u > cc["u"]["max"]:
            if self.relay.value():
                print("UH", self.val_u, file=sys.stderr)
            return False
        if self.val_i < cc["i"]["min"]:
            if self.relay.value():
                print("IL", self.val_i, file=sys.stderr)
            return False
        if self.val_i > cc["i"]["max"]:
            if self.relay.value():
                print("IH", self.val_i, file=sys.stderr)
            return False
        return True

    def stat(self, r=False):
        res = dict(
            u=self.val_u,
            i=self.val_i,
            w=dict(s=self.sum_w, n=self.n_w),
            r=dict(s=self.relay.value(), f=self.relay_force, l=self.live),
            gen=self.gen,
        )
        if r:
            self.sum_w = 0
            self.n_w = 0
        return res

    async def set_relay_force(self, st):
        self.relay_force = st
        if st is not None:
            self.relay.value(st)
            await self.send_rly_state("forced")
        else:
            await self.send_rly_state("auto")
            if not self.relay.value():
                self.sw_ok = False
                self.t_sw = ticks_add(self.t, self.cfg["relay"]["t"])
                print("DLY", self.cfg["relay"]["t"], file=sys.stderr)

    def live_state(self, live: bool):
        if self.live == live:
            return
        self.live = live
        if not live:
            self.relay.off()
            await self.send_rly_state("Live Fail")

    def set_live(self):
        self.live_flag.set()

    async def live_task(self):
        while True:
            try:
                await wait_for_ms(self.cfg["poll"]["k"], self.live_flag.wait)
            except TimeoutError:
                self.live_state(False)
            else:
                self.live_flag = Event()
                self.live_state(True)

    async def config_updated(self, cfg):
        old_u_scale, old_u_offset = self.adc_u_scale, self.adc_u_offset
        old_i_scale, old_i_offset = self.adc_i_scale, self.adc_i_offset
        self._set_scales()
        self.val_u = (
            self.val_u - old_u_offset
        ) / old_u_scale * self.adc_u_scale + self.adc_u_offset
        self.val_i = (
            self.val_i - old_i_offset
        ) / old_i_scale * self.adc_i_scale + self.adc_i_offset

        await self.send_work()

    async def send_work(self):
        if not self.cmd:
            return
        res = dict(
            w=self.sum_w,
            n=self.n_w,
        )
        self.sum_w = 0
        self.n_w = 0
        await self.cmd.request.send_nr([self.cmd.name, "work"], **res)

    def _set_scales(self):
        c = self.cfg["batt"]
        self.adc_u_scale = c["u"]["scale"]
        self.adc_u_offset = c["u"]["offset"]
        self.adc_i_scale = c["i"]["scale"]
        self.adc_i_offset = c["i"]["offset"]

    async def run(self, cmd):
        c = self.cfg["batt"]
        self.cmd = cmd
        self.adc_u = M.ADC(M.Pin(c["u"]["pin"]))
        self.adc_i = M.ADC(M.Pin(c["i"]["pin"]))
        self.adc_ir = M.ADC(M.Pin(c["i"]["ref"]))
        self.relay = M.Pin(self.cfg["relay"]["pin"], M.Pin.OUT)
        self.sum_w = 0
        self.n_w = 0
        self.relay_force = None
        self.live = self.relay.value()
        self.live_flag = Event()
        # we start off with the current relay state
        # so a soft reboot won't toggle the relay

        self._set_scales()

        def sa(a, n=10):
            s = 0
            for _ in range(n):
                s += a.read_u16()
            return s / n

        self.val_u = sa(self.adc_u) * self.adc_u_scale + self.adc_u_offset
        self.val_i = (sa(self.adc_i) - sa(self.adc_ir)) * self.adc_i_scale + self.adc_i_offset

        self.sw_ok = False

        self.t = ticks_ms()
        self.t_sw = ticks_add(ticks_ms(), self.cfg["relay"]["t1"])

        async with TaskGroup() as tg:
            await tg.spawn(self.live_task, _name="bms.live")
            await self._run()

    async def _run(self):
        xmit_n = 0
        while True:
            self.t = ticks_add(self.t, self.cfg["poll"]["t"])

            if not self.sw_ok:
                if ticks_diff(self.t, self.t_sw) > 0:
                    self.sw_ok = True
                    xmit_n = 0

            if await self._check():
                if (
                    self.sw_ok
                    and self.live
                    and self.relay_force is None
                    and not self.relay.value()
                ):
                    self.relay.on()
                    await self.send_rly_state("Check OK")
                    xmit_n = 0

            elif self.live and self.relay_force is None and self.relay.value():
                self.relay.off()
                await self.send_rly_state("Check Fail")
                self.t_sw = ticks_add(self.t, self.cfg["relay"]["t"])
                self.sw_ok = False
                xmit_n = 0

            xmit_n -= 1
            if xmit_n <= 0 or self.xmit_evt.is_set:
                if self.gen >= 99:
                    self.gen = 10
                else:
                    self.gen += 1
                self.xmit_evt.set()
                self.xmit_evt = Event()
                xmit_n = self.cfg["poll"]["n"]

            t = ticks_ms()
            td = ticks_diff(self.t, t)
            if td > 0:
                if self.n_w >= 1000:
                    await self.send_work()
                await sleep_ms(td)
            else:
                self.t = t

    async def send_rly_state(self, txt):
        self.xmit_evt.set()
        print("RELAY", self.relay.value(), txt, file=sys.stderr)


class BMSCmd(BaseCmd):
    def __init__(self, parent, name, cfg, gcfg):
        super().__init__(parent)
        self.bms = BMS(cfg, gcfg)
        self.name = name

    async def run(self):
        try:
            await self.bms.run(self)
        finally:
            self.bms = None

    async def config_updated(self, cfg):
        await super().config_updated(cfg)
        await self.bms.config_updated(cfg)

    async def cmd_rly(self, st=NotGiven):
        """
        Called manually, but also irreversibly when there's a "hard" cell over/undervoltage
        """
        if st is NotGiven:
            return self.bms.relay.value(), self.bms.relay_force
        await self.bms.set_relay_force(st)

    async def cmd_info(self, gen=-1, r=False):
        if self.bms.gen == gen:
            await self.bms.xmit_evt.wait()
        return self.bms.stat(r)

    def cmd_live(self):
        self.bms.set_live()
