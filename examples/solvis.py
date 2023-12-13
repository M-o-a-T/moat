#!/usr/bin/python3

# this program controls a SolvisMax+SolvisLea combination "manually",
# because the Solvis conttoller is too plain stupid for my taste.

import sys
sys.path.insert(0,".")

import io
import time
import anyio
import RPi.GPIO as GPIO
import asyncclick as click
import logging
from pprint import pprint

from moat.lib.pid import CPID

from moat.util import yload,yprint,attrdict, PathLongener, P
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
    # offsets to destination temperature
    water: 3
    heat: 3
    more: 5  # output temperature offset
    max: 62  # don't try for more
    low:
        water: 1
        heat: 1
output:
    flow:
        pin: 4
        freq: 200
        path: !P heat.s.pump.pid
sensor:
    pump:
        in: !P heat.s.pump.temp.in   # t_in
        out: !P heat.s.pump.temp.out # t_out
        flow: !P heat.s.pump.flow    # r_flow: flow rate
        ice: !P heat.s.pump.de_ice   # m_ice
    buffer:
        top: !P heat.s.buffer.temp.water   # tb_water
        heat: !P heat.s.buffer.temp.heat   # tb_heat
        mid: !P heat.s.buffer.temp.mid     # tb_mid
        low: !P heat.s.buffer.temp.return  # tb_low
    error: !P heat.s.pump.err
setting:
    heat:
        day: !P heat.s.heat.temp        # c_heat
        night: !P heat.s.heat.temp_low  # c_heat_night
        mode: !P heat.s.heat.mode       # m_heat  # 5:standby 2:auto 3:day 4:night
    water: !P heat.s.water.temp         # c_water
    passthru: !P heat.s.pump.pass       # m_passthru
lim:
    flow:
        min: 5
    power:
        min: .04
        off: .2
        time: 60
cmd:
    flow: !P heat.s.pump.rate.cmd       # c_flow
    main: !P home.ass.dyn.switch.heizung.wp.cmd  # c_main
    mode:
      path: !P heat.s.pump.cmd.mode       # write
      on: 3
      off: 0
    power: !P heat.s.pump.cmd.power
feedback:
    main: !P home.ass.dyn.switch.heizung.wp.state
misc:
    init_timeout: 5
    de_ice: 12  # flow rate when de-icing
    stop:
        flow: 10
        delta: 3
    start:
      flow: 10  # flow rate when starting up
      power: 0.15
      delta: 2
pid:
    flow:
        # direct flow rate control for the pump
        # input: flow rate
        # output: PWM for the flow pump
        p: 0.003
        i: 0.0003
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

    load:
        # input: buffer temperature
        # output: heat exchanger load
        ## Add as much load as required to keep the buffer temperature up.
        p: 0.01
        i: 0.001
        d: 0.0
        tf: 0.0

        min: .04
        max: 1

        # no setpoint change, always zero
        # 
        # 50: 5 /min
        # 
        factor: 0
        offset: 0

        # state attr
        state: p_load

    limit:
        # input: exchanger output temperature
        # output: heat exchanger load
        ## Add as much load as required to keep the output temperature up.
        p: 0.02
        i: 0.0025
        d: 0.0
        tf: 0.0

        min: .04
        max: 1

        # setpoint change
        # 65: 20 /min
        # 50: 5 /min
        # 
        factor: 1
        offset: -45

        # state attr
        state: p_limit

    pump:
        # input: exchanger output temperature
        # output: PWM for the flow pump
        ## Adjust the flow to keep the output temperature within range.
        p: -0.005
        i: -0.0005
        d: 0.0
        tf: 0.0

        min: .2
        max: 1

        factor: 0
        offset: 0

        # state attr
        state: p_pump

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
        self.load_prev = -1
        self.pump_prev = -1

        try:
            with open(cfg.state,"r") as sf:
                self.state = yload(sf, attr=True)
        except EnvironmentError:
            self.state = attrdict()

        # calculated pump flow rate, 0…1
        self.cp_flow = None
        self.m_errors = set()

        self.pid_load = CPID(self.cfg.pid.load, self.state)
        self.pid_limit = CPID(self.cfg.pid.limit, self.state)
        self.pid_pump = CPID(self.cfg.pid.pump, self.state)
        self.pid_flow = CPID(self.cfg.pid.flow, self.state)

    @property
    def cl(self):
        return self._cl

    @property
    def cfg(self):
        return self._cfg

    # async def set_flow_pwm(self, rate):
    # added by .run_flow

    async def set_load(self, p):
        if p < self.cfg.lim.power.min:
            if self.load_prev:
                print("*** OFF")
            await self.cl.set(self.cfg.cmd.power, value=0, idem=True)
            await self.cl.set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off, idem=True)
            self.load_prev = p
        else:
            await self.cl.set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.on, idem=True)
            await self.cl.set(self.cfg.cmd.power, value=min(p,1), idem=True)
            self.load_prev = 0

    async def run_pump(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        main_ = None
        run = self.state.get("run",0)
        # 0 off; 1 go_up, 2 up, 3 go_down
        # TODO charge the hot water part separately

        orun = None
        oice = None
        while True:
            if orun == run:
                task_status.started()
                task_status = anyio.TASK_STATUS_IGNORED
                await self.wait()
            else:
                print("RUNMODE",run)
                if run == -1:  # std
                    self.cp_flow = None
                    t_low = time.monotonic()
                    if orun is not None:
                        self.pid_pump.reset()
                        self.pid_limit.reset()
                        self.pid_load.reset()
                        self.state.load_last = None
                elif run == -2:
                    self.cp_flow = self.cfg.misc.stop.flow
                    await self.cl.set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off)
                    await self.cl.set(self.cfg.cmd.power, value=0)
                orun = run

            if not self.m_ice:
                req = bool(self.c_main) and not bool(self.m_errors)
                if main_ != req:
                    await self.cl.set(self.cfg.feedback.main, req)
                    main_ = req

            t_max = self.c_water+self.cfg.adj.water
            t_min = self.c_water+self.cfg.adj.low.water
            t_cur = self.tb_water
            if self.m_heat < 5:  # 5:standby 2:auto 3:day 4:night
                t_max = max(t_max, self.c_heat+self.cfg.adj.heat)
                t_min = max(t_min, self.c_heat+self.cfg.adj.low.heat)
                t_cur = min(t_cur,self.tb_heat)
            t_max_out = min(self.cfg.adj.max, t_max+self.cfg.adj.more)

            if run != -1:
                print(f"cur={t_cur :.01f} min={t_min :.01f} max={t_max :.01f} max_out={t_max_out :.01f}")
            if not main_:
                # turn me off
                if run and run != -2:
                    run = -2
                    continue
            elif t_cur < (t_min+t_max)/2:
                if not run:
                    run = 1
                    continue
            self.state.run = run


            if oice and not self.m_ice:
                print("******** NO ICE *********")
                run=2
                continue

            if self.m_ice:
                if not oice:
                    print("******** ICE *********")
                    self.pid_flow.setpoint(self.cfg.misc.de_ice)
                if run == -1:
                    self.cp_flow = None
                    l_flow = self.pid_flow(self.r_flow)
                    l_temp = self.pid_pump(self.t_out)
                    await self.set_flow_pwm(max(l_flow,l_temp), quiet=True)
                else:
                    self.cp_flow = self.cfg.misc.de_ice

            elif run == 0: # off
                self.cp_flow = None
                await self.set_flow_pwm(0)
                await self.set_load(0)

            elif run == 1:
                # Startup A: start the load pump
                self.pid_flow.reset()
                self.state.last_pump = None
                self.cp_flow = self.cfg.misc.start.flow
                if self.r_flow > self.cfg.misc.start.flow*3/4:
                    run = 2
                    continue

            elif run == 2:
                # Startup B: get some power in until we have a delta
                await self.set_load(self.cfg.misc.start.power)
                if self.t_out-self.t_in > self.cfg.misc.start.delta:
                    run = -1
                    continue

            elif run == -1:
                self.d_flow = True
                # "Normal" (continuous) operations.
                last = self.state.get("load_last",None)

                if self.pid_load.state.get("setpoint",None) != t_max:
                    logger.info("Load SET %.03f",t_max)
                if self.pid_limit.state.get("setpoint",None) != t_max_out:
                    logger.info("Limit SET %.03f",t_max_out)
                if self.pid_pump.state.get("setpoint",None) != t_max:
                    logger.info("Pump SET %.03f",t_max)
                self.pid_load.setpoint(t_max)
                self.pid_limit.setpoint(t_max_out)
                self.pid_pump.setpoint(t_max)
                
                l_pump = self.pid_pump(self.t_out, last=self.state.get("last_pump",None))
                self.state.last_pump = l_pump
                self.pid_flow(self.r_flow, last=l_pump)

                l_load = self.pid_load(t_cur, last=last)
                l_limit = self.pid_limit(self.t_out, last=last)
                lim=min(l_load,l_limit)
                print(f"cur={t_cur :.01f} min={t_min :.01f} max={t_max :.01f} max_out={t_max_out :.01f} Pump={l_pump :.03f} load={l_load :.03f}/{l_limit :.03f}")
                await self.set_load(lim)
                await self.set_flow_pwm(l_pump, quiet=True)
                self.state.load_last = lim

                if lim < self.cfg.lim.power.off:
                    if time.monotonic()-t_low > self.cfg.lim.power.time or self.tb_mid > (t_min*2+t_max)/3:
                        run = -2
                else:
                    t_low = time.monotonic()

            elif run == -2:  # shutdown
                if self.t_out-self.t_in < self.cfg.misc.stop.delta:
                    run = 0


    async def run_flow(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        try:
            path = self.cfg.output.flow.path
        except AttributeError:
            pin = self.cfg.output.flow.pin
            GPIO.setup(pin, GPIO.OUT)
            port = GPIO.PWM(pin, 200)  # frequency=50Hz
            port.start(0)
            async def set_pwm(r, quiet=False):
                if not quiet:
                    if self.pump_prev != r:
                        logger.info("PUMP=%f",r)
                self.pump_prev = r
                port.ChangeDutyCycle(100*r)
        else:
            async def set_pwm(r, quiet=False):
                if not quiet:
                    if self.pump_prev != r:
                        logger.info("PUMP=%f",r)
                self.pump_prev = r
                await self.cl.set(path,value=r, idem=True)

        warned = False
        self.set_flow_pwm = set_pwm
        task_status.started()

        while True:
            await self.wait()
            if self.m_passthru is not False:
                await set_pwm(self.m_passthru)
                self.pid_flow.reset()
                continue
            if self.d_flow:
                self.pid_flow.reset()
                continue

#           if self.t_out - self.t_in < 2 and not self.cp_heat:
#               port.ChangeDutyCycle(0)
#               continue

            r = self.cp_flow
            if r is None:
                continue
            elif r < self.cfg.lim.flow.min/2:
                await set_pwm(0)
                breakpoint()
                print("DUTY","OFF")
            else:
                if self.pid_flow.state.get("setpoint",None) != r:
                    logger.info("PUMP SET %.03f",r)
                    self.pid_flow.setpoint(r)
                warned = False

                res = self.pid_flow(self.r_flow, last=self.state.get("last_pump",None))
                self.state.last_pump = res
                self.pid_pump(self.t_out, last=res)
                await set_pwm(res)
                print("DUTY",res,"in:",self.r_flow,"for:",r)
            

    def has(self, name, value):
        setattr(self,name,value)
        if (evt := self._sigs.get(name)) is not None:
            evt.set()
        self.trigger()

    def trigger(self):
        self._got.set()
        self._got = anyio.Event()

    async def err_mon(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        async with self.cl.watch(self.cfg.sensor.error, long_path=False,fetch=True) as msgs:
            task_status.started()
            errs = self.m_errors
            err_base = P("pump")
            pl = PathLongener(())
            async for m in msgs:
                if "value" not in m:
                    continue
                pl(m)
                err = err_base+m.path
                was = bool(errs)
                if m.value:
                    errs.add(err)
                else:
                    errs.discard(err)
                if was or errs:
                    print("****** ERROR ********",errs)
                self.trigger()


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

    async def _kv(self,p,v,*,task_status=anyio.TASK_STATUS_IGNORED):
        self._want.add(v)
        miss = False
        task_status.started()
        async with self._cl.watch(p,max_depth=0,fetch=True) as msgs:
            async for m in msgs:
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
                    logger.debug("Value: %r:%r", p,m.value)
                    if miss:
                        miss = False
                        self._want.remove(v)
                    self.has(v,m.value)

    async def off(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        async with anyio.create_task_group() as tg:
            await tg.start(self.run_flow)
            run = self.state.get("run",0)
            if run:
                self.state.run = -2

            await self.set_load(0)
            if self.t_out-self.t_in > self.cfg.misc.stop.delta:
                self.cp_flow = self.cfg.misc.stop.flow
                while self.t_out-self.t_in > self.cfg.misc.stop.delta:
                    logger.info("Waiting. %f %f",self.t_out,self.t_in)
                    await self.wait()

            await self.set_flow_pwm(0)

            tg.cancel_scope.cancel()
        await self.set_flow_pwm(0)
        self.state.run = 0
        await self.save()

    async def run(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        cfg = self._cfg
        async with anyio.create_task_group() as tg:
            await tg.start(self.run_flow)
            await tg.start(self.run_pump)
            task_status.started()

    async def run_init(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        cfg = self._cfg
        async with anyio.create_task_group() as tg:
            await tg.start(self._kv, cfg.cmd.flow, "c_flow")
            await tg.start(self._kv, cfg.cmd.main, "c_main")
            await tg.start(self._kv, cfg.setting.heat.day, "c_heat")
            await tg.start(self._kv, cfg.setting.heat.night, "c_heat_night")
            await tg.start(self._kv, cfg.setting.heat.mode, "m_heat")
            await tg.start(self._kv, cfg.setting.water, "c_water")
            await tg.start(self._kv, cfg.setting.passthru, "m_passthru")
            await tg.start(self._kv, cfg.sensor.pump["in"], "t_in")
            await tg.start(self._kv, cfg.sensor.pump["out"], "t_out")
            await tg.start(self._kv, cfg.sensor.pump.flow, "r_flow")
            await tg.start(self._kv, cfg.sensor.pump.ice, "m_ice")
            await tg.start(self._kv, cfg.sensor.buffer.top, "tb_water")
            await tg.start(self._kv, cfg.sensor.buffer.heat, "tb_heat")
            await tg.start(self._kv, cfg.sensor.buffer.mid, "tb_mid")
            await tg.start(self._kv, cfg.sensor.buffer.low, "tb_low")

            try:
                with anyio.fail_after(self.cfg.misc.init_timeout):
                    await self.all_done()
            except TimeoutError:
                raise ValueError("missing:"+repr(self._want)) from None
            task_status.started()
            pprint(vars(self))

    async def saver(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        task_status.started()
        while True:
            await anyio.sleep(10)
            await self.save()
            await self.wait()

    async def save(self):
        logger.debug("Saving")
        f = anyio.Path(self.cfg.state)
        fn = anyio.Path(self.cfg.state+".n")
        fs = io.StringIO()
        yprint(self.state,fs)
        await fn.write_text(fs.getvalue())
        await fn.rename(f)

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
@click.option("-c","--config",type=click.File("r"), help="config file")
async def main(ctx, config):
    ctx.obj = attrdict()
    if config is not None:
        cfg = yload(config,attr=True)
    else:
        cfg = yload(CFG,attr=True)
    ctx.obj.cfg = cfg
    pass

@main.command
@click.pass_obj
async def run(obj):
    async with open_client(**mcfg.kv) as cl, anyio.create_task_group() as tg:
        d = Data(obj.cfg,cl)
        await tg.start(d.run_init)
        await tg.start(d.err_mon)
        await tg.start(d.run)
        await tg.start(d.saver)


@main.command
@click.pass_obj
async def pwm(obj):
    """
    Run backgrounds task for software PWM outputs.
    """
    async with open_client(**mcfg.kv) as cl, anyio.create_task_group() as tg:
        for k,p in obj.cfg.output.items():
            tg.start_soon(_run_pwm,cl,k,p)

async def _run_pwm(cl,k,v):
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
async def off(obj):
    async with open_client(**mcfg.kv) as cl, anyio.create_task_group() as tg:
        d = Data(obj.cfg,cl)
        await tg.start(d.run_init)
        await d.off()
        tg.cancel_scope.cancel()

if __name__ == "__main__":
    click.anyio_backend="trio"
    main()
