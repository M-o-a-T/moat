#!/usr/bin/python3

# this program controls a SolvisMax+SolvisLea combination "manually",
# because the Solvis conttoller is too plain stupid for my taste.

import sys
sys.path.insert(0,".")

import os
import time
import anyio
import RPi.GPIO as GPIO
import asyncclick as click
import logging
from moat.lib.pid import CPID

from moat.util import yload,yprint,attrdict
from moat.kv.client import open_client

FORMAT = (
    "%(levelname)s %(pathname)-15s %(lineno)-4s %(message)s"
)
logging.basicConfig(level=logging.INFO,format=FORMAT)

GPIO.setmode(GPIO.BCM)
logger = logging.root

CFG="""
state: "/tmp/solvis.state"
adj:
    water: 3
    heat: 2
output:
    flow:
        pin: 4
        freq: 200
        path: !P heat.s.pump.pid
sensor:
    pump:
        in: !P heat.s.pump.temp.in   # t_in
        out: !P heat.s.pump.temp.out # t_out
        flow: !P heat.s.pump.flow    # r_flow
    buffer:
        top: !P heat.s.buffer.temp.water   # tb_water
        heat: !P heat.s.buffer.temp.heat   # tb_heat
        mid: !P heat.s.buffer.temp.mid     # tb_mid
        low: !P heat.s.buffer.temp.return  # tb_low
setting:
    heat:
        day: !P heat.s.heat.temp        # c_heat
        night: !P heat.s.heat.temp_low  # c_heat_night
        mode: !P heat.s.heat.mode       # m_heat  # 3:standby 2:auto 3:day 4:night
    water: !P heat.s.water.temp         # c_water
    passthru: !P heat.s.pump.pass       # m_passthru
lim:
    flow:
        min: 5
cmd:
    flow: !P heat.s.pump.rate.cmd       # c_flow
pid:
    flow:
        p: 0.01
        i: 0.001
        d: 0.0
        tf: 0.0

        min: .1
        max: .95

        # setpoint change
        # .8 == 20 l/min
        factor: .04
        offset: 0

        # state attr
        state: p_flow
"""


with open("/etc/moat/moat.cfg","r") as _f:
    mcfg = yload(_f, attr=True)

class Data:
    def __init__(self, cfg, cl):
        self._cfg = cfg
        self._cl = cl
        self._got = anyio.Event()
        self._want = set()
        self._sigs = {}

        try:
            with open(cfg.state,"r") as sf:
                self.state = yload(sf, attr=True)
        except EnvironmentError:
            self.state = attrdict()

        # calculated pump flow rate, 0…1
        self.cp_flow = None
        self.pid_flow = None

    @property
    def cl(self):
        return self._cl

    @property
    def cfg(self):
        return self._cfg

    async def run_pump(self, *, task_status):
        try:
            path = self.cfg.output.flow.path
        except AttributeError:
            pin = self.cfg.output.flow.pin
            GPIO.setup(pin, GPIO.OUT)
            port = GPIO.PWM(pin, 200)  # frequency=50Hz
            port.start(0)
            async def set_pwm(r):
                port.ChangeDutyCycle(100*r)
        else:
            async def set_pwm(r):
                await self.cl.set(path,value=r, idem=True)
        warned = False
        task_status.started()

        while True:
            await self.wait()
            if self.m_passthru:
                await set_pwm(self.c_flow)
                continue

#           if self.t_out - self.t_in < 2 and not self.cp_heat:
#               port.ChangeDutyCycle(0)
#               continue
            t_max = max(
                    self.c_heat+self.cfg.adj.heat,
                    self.c_water+self.cfg.adj.water,
                    )
            if (pid := self.pid_flow) is None:
                self.pid_flow = pid = CPID(self.cfg.pid.flow, self.state)

            r = self.cp_flow if self.c_flow is None else self.c_flow
            if r is None:
                if not warned:
                    logger.warning("No flow known")
                    warned = True
                continue
            elif r < self.cfg.lim.flow.min/2:
                await set_pwm(0)
                print("DUTY","OFF")
            else:
                pid.setpoint(r)
                warned = False
                res = pid(self.r_flow)
                await set_pwm(res)
                print("DUTY",res,"in:",self.r_flow,"for:",r)
            

    def has(self, name, value):
        setattr(self,name,value)
        if (evt := self._sigs.get(name)) is not None:
            evt.set()
        self._got.set()
        self._got = anyio.Event()

    async def wait(self):
        await self._got.wait()

    async def wait_for(self, v):
        if (evt := self._sigs.get(v)) is not None:
            await evt.wait()
        else:
            self._sigs[v] = evt = anyio.Event()
            await evt.wait()
            del self._sigs[v]

    async def all_done(self):
        while self._want:
            print("Waiting",self._want)
            await self._got.wait()

    async def _kv(self,p,v,*,task_status=None):
        self._want.add(v)
        miss = False
        if task_status is not None:
            task_status.started()
        async with self._cl.watch(p,max_depth=0,fetch=True) as msgs:
            async for m in msgs:
                print(m)
                if m.get("state","") == "uptodate":
                    if hasattr(self,v):
                        miss = False
                        self._want.remove(v)
                        if not self._want:
                            self._got.set()
                            self._got = anyio.Event()

                    else:
                        logger.warning("Missing: %r:%r", p,v)
                        miss = True
                elif "value" not in m:
                    logger.warning("Unknown: %r:%r: %r", p,v,m)
                else:
                    logger.info("Value: %r:%r", p,m.value)
                    if miss:
                        miss = False
                        self._want.remove(v)
                    self.has(v,m.value)

    async def run(self, *, task_status):
        cfg = self._cfg
        async with anyio.create_task_group() as tg:
            await tg.start(self.run_pump)
            task_status.started()

    async def run_init(self, *, task_status):
        cfg = self._cfg
        async with anyio.create_task_group() as tg:
            await tg.start(self._kv, cfg.cmd.flow, "c_flow")
            await tg.start(self._kv, cfg.setting.heat.day, "c_heat")
            await tg.start(self._kv, cfg.setting.heat.night, "c_heat_night")
            await tg.start(self._kv, cfg.setting.heat.mode, "m_heat")
            await tg.start(self._kv, cfg.setting.water, "c_water")
            await tg.start(self._kv, cfg.setting.passthru, "m_passthru")
            await tg.start(self._kv, cfg.sensor.pump["in"], "t_in")
            await tg.start(self._kv, cfg.sensor.pump["out"], "t_out")
            await tg.start(self._kv, cfg.sensor.pump.flow, "r_flow")
            await tg.start(self._kv, cfg.sensor.buffer.top, "tb_water")
            await tg.start(self._kv, cfg.sensor.buffer.heat, "tb_heat")
            await tg.start(self._kv, cfg.sensor.buffer.mid, "tb_mid")
            await tg.start(self._kv, cfg.sensor.buffer.low, "tb_low")

            try:
                with anyio.fail_after(5):
                    await self.all_done()
            except TimeoutError:
                raise ValueError("missing:"+repr(self._want)) from None
            task_status.started()
            yprint({k:v for k,v in vars(self).items() if not k.startswith("_")})

    async def saver(self, *, task_status):
        task_status.started()
        while True:
            await anyio.sleep(10)
            with open(self.cfg.state+"n","w") as sf:
                yprint(self.state,sf)
            os.rename(self.cfg.state+"n",self.cfg.state)

#GPIO.setup(12, GPIO.OUT)
# 
#p = GPIO.PWM(12, .2)  # frequency=50Hz
#p.start(50)
#try:
#    while 1:
#        time.sleep(10)
#except KeyboardInterrupt:
#    p.stop()
#    GPIO.cleanup()

@click.group
@click.pass_context
async def main(ctx):
    ctx.obj = attrdict()
    ctx.obj.cfg = cfg = yload(CFG,attr=True)
    pass

@main.command
@click.pass_obj
async def run(obj):
    cfg = obj.cfg
    async with open_client(**mcfg.kv) as cl, anyio.create_task_group() as tg:
        d = Data(cfg,cl)
        await tg.start(d.run_init)
        await tg.start(d.run)
        await tg.start(d.saver)

async def _run_pid(cl,k,v):
    GPIO.setup(v.pin, GPIO.OUT)
    port = GPIO.PWM(v.pin, v.get("freq",200))
    port.start(0)
    async with cl.watch(v.path,max_depth=0,fetch=True) as msgs:
        async for m in msgs:
            if m.get("state","") == "uptodate":
                pass
            elif "value" not in m:
                logger.warning("Unknown: %s:%r: %r", k,v,m)
            else:
                logger.info("Value: %s:%r", k,m.value)
                port.ChangeDutyCycle(100*m.value)

@main.command
@click.pass_obj
async def pwm(obj):
    async with open_client(**mcfg.kv) as cl, anyio.create_task_group() as tg:
        for k,p in obj.cfg.output.items():
            tg.start_soon(_run_pid,cl,k,p)

if __name__ == "__main__":
    main()
