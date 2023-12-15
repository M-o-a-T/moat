#!/usr/bin/python3

# This program controls a SolvisMax+SolvisLea combination "manually"
# because the SolvisMax controller doesn't support a heap of features I need.
# 
# See the accompanying .rst file for details.
#
import sys
sys.path.insert(0,".")

import io
import time
import anyio
import RPi.GPIO as GPIO
import asyncclick as click
import logging
from enum import IntEnum,auto

from moat.lib.pid import CPID

from moat.util import yload,yprint,attrdict, PathLongener, P,to_attrdict,to_attrdict
from moat.kv.client import open_client

FORMAT = (
    "%(levelname)s %(pathname)-15s %(lineno)-4s %(message)s"
)
logging.basicConfig(level=logging.INFO,format=FORMAT)

GPIO.setmode(GPIO.BCM)
logger = logging.root

class Run(IntEnum):
    # nothing happens
    off=0
    # wait for pump to be ready after doing whatever
    wait_time=auto()
    # wait for throughput to show up
    wait_flow=auto()
    # wait for decent throughput
    flow=auto()
    # wait for pump to draw power
    wait_power=auto()
    # wait for outflow-inflow>2
    temp=auto()
    # operation
    run=auto()
    # wait for outflow-inflow<2 for n seconds, cool down
    down=auto()

CFG="""
state: "/tmp/solvis.state"
adj:
    # offsets to destination temperature
    water: 3
    heat: 3
    more: 4  # output temperature offset
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
    power: !P heat.s.pump.power  # c_power
setting:
    heat:
      day: !P heat.s.heat.temp        # c_heat
      night: !P heat.s.heat.temp_low  # c_heat_night
      mode:
        path: !P heat.s.heat.mode.cmd    # 5:standby 2:auto 3:day 4:night
        on: 3
        off: 5
        delay: 30
    water: !P heat.s.water.temp         # c_water
    passthru: !P heat.s.pump.pass       # m_passthru
lim:
    flow:
        min: 5
    power:
        min: .04
        off: .2   # power cutoff if the buffer is warm enough
        time: 300  # must run at least this long
cmd:
    flow: !P heat.s.pump.rate.cmd       # c_flow
    main: !P home.ass.dyn.switch.heizung.wp.cmd  # cm_main
    heat: !P home.ass.dyn.switch.heizung.main.cmd  # cm_heat
    mode:
      path: !P heat.s.pump.cmd.mode       # write
      on: 3
      off: 0
    power: !P heat.s.pump.cmd.power
feedback:
    main: !P home.ass.dyn.switch.heizung.wp.state
    heat: !P home.ass.dyn.switch.heizung.main.state
misc:
    init_timeout: 5
    de_ice: 17  # flow rate when de-icing
    stop:
      flow: 10  # or more if the max outflow temperature wants us to
      delta: 3  # outflow-inflow: if less than .delta, the pump can be turned off
    start: # conditions when starting up
      delay: 330  # 10min
      flow:
        init:
          rate: 6
          pwm: .25
        power:
          rate: 15
          pwm: .4
        run: 15
      power: 0.1
      delta: 2  # outflow-inflow: if more than .delta, we start the main control algorithm
      # TODO add pump power uptake, to make sure this is no fluke
    min_power: 0.9
pid:
    flow:
        ## direct flow rate control for the pump
        # input: desired flow rate
        # output: PWM for the flow pump
        p: 0.02   # half of 1/20
        i: 0.0003
        d: 0.0
        tf: 0.0

        min: .25
        max: .95

        # setpoint change
        # .8 == 20 l/min
        factor: 0 # .04
        offset: 0

        # state attr
        state: p_flow

    pump:
        ## indirect flow rate control. The heat pump delivers some amount of energy;
        ## we want the flow rate to be such that the temperature of the outflow is
        ## what we want. Too high and the efficiency suffery; too low and we don't get
        ## the temperature we want.
        #
        # setpoint: desired buffer temperature, plus offset
        # input: exchanger output temperature
        # output: PWM for the flow pump
        ## Adjust the flow to keep the output temperature within range.
        p: -0.06
        i: -0.001
        d: 0.0
        tf: 0.0

        min: .2
        max: 1

        factor: 0
        offset: 0

        # state attr
        state: p_pump

    load:
        ## Primary heat exchanger control. We want the buffer temperature to be at a certain value.
        ## 
        # setpoint: desired buffer temperature
        # input: buffer temperature
        # output: heat exchanger load
        ## Add as much load as required to keep the buffer temperature up.
        p: 0.08
        i: 0.0005
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
        ## Secondary heat exchanger control. We don't want more load than the pump can transfer
        ## to the buffer, otherwise the system overheats.
        #
        # setpoint: desired buffer temperature plus adj.more
        # input: exchanger output temperature
        # output: heat exchanger load
        p: 0.05
        i: 0.0007
        d: 0.0
        tf: 0.0

        min: .04
        max: 1

        # setpoint change
        # 65: 20 /min
        # 50: 5 /min
        # 
        factor: 0 # 1
        offset: 0 # -45

        # state attr
        state: p_limit

"""


with open("/etc/moat/moat.cfg","r") as _f:
    mcfg = yload(_f, attr=True)

class Data:
    force_on=False

    def __init__(self, cfg, cl, record=None):
        self._cfg = cfg
        self._cl = cl
        self._got = anyio.Event()
        self._want = set()
        self._sigs = {}
        self.load_prev = -1
        self.record=record

        try:
            with open(cfg.state,"r") as sf:
                self.state = yload(sf, attr=True)
        except EnvironmentError:
            self.state = attrdict()

        # calculated pump flow rate, 0…1
        self.cp_flow = None
        self.m_errors = {}

        self.pid_load = CPID(self.cfg.pid.load, self.state)
        self.pid_limit = CPID(self.cfg.pid.limit, self.state)
        self.pid_pump = CPID(self.cfg.pid.pump, self.state)
        self.pid_flow = CPID(self.cfg.pid.flow, self.state)
        self.state.setdefault("heat_ok",False)

        try:
            path = self.cfg.output.flow.path
        except AttributeError:
            pin = self.cfg.output.flow.pin
            GPIO.setup(pin, GPIO.OUT)
            self._flow_port = port = GPIO.PWM(pin, 200)
            port.start(0)
            async def set_flow_pwm(r):
                self.state.last_pwm = r
                port.ChangeDutyCycle(100*r)
        else:
            async def set_flow_pwm(r):
                self.state.last_pwm = r
                await self.cl.set(path,value=r, idem=True)
        self.set_flow_pwm = set_flow_pwm

    @property
    def time(self):
        try:
            return self.TS
        except AttributeError:
            return time.monotonic()

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
        cm_main = None
        run = Run(self.state.get("run",0))
        # 0 off; 1 go_up, 2 up, 3 go_down
        # TODO charge the hot water part separately
        tlast=0

        orun = None
        m_ice = False
        flow_on = None
        cm_main = None
        cm_heat = None

        while True:
            #
            # Part 1: what to do when a state changes
            #
            # check for inappropriate state changes
            #
            if orun == run:
                pass
            elif orun is None:
                pass
            elif run.value == orun.value+1:
                pass
            elif orun != Run.off and run == Run.down:
                pass
            elif orun == Run.down and run == Run.off:
                pass
            else:
                raise ValueError(f"Cannot go from {orun} to {run}")

            # Handle state changes

            # redirect
            if run == Run.off:
                if orun not in (Run.off,Run.wait_time,Run.wait_flow,Run.wait_power,Run.down):
                    run = Run.down

            # Report
            if orun == run:
                pass
            elif orun is None:
                print(f"*** STATE: {run.name}")
            else:
                print(f"*** STATE: {orun.name} >> {run.name}")

            # Leaving a state
            if orun is None:  # fix stuff for startup
                # assume PIDs are restored from state
                # assume PWM is stable
                if run == Run.run:
                    last = self.state.get("load_last",None)
                    if last is not None:
                        await self.set_load(last)

            elif orun == run:  # no change
                pass

            elif orun == Run.down:
                pass

            # Entering a state
            if orun == run:  # no change
                task_status.started()
                task_status = anyio.TASK_STATUS_IGNORED
                await self.wait()

            elif run == Run.off:  # nothing happens
                await self.set_flow_pwm(0)
                await self.set_load(0)
                self.state.last_pwm = None

            elif run == Run.wait_time:  # wait for the heat pump to be ready after doing whatever
                await self.set_flow_pwm(0)
                await self.set_load(0)

            elif run == Run.wait_flow:  # wait for flow
                await self.set_flow_pwm(self.cfg.misc.start.flow.init.pwm)

            elif run == Run.flow:  # wait for decent throughput
                pass

            elif run == Run.wait_power:  # wait for pump to draw power
                await self.set_load(self.cfg.misc.start.power)

            elif run == Run.temp:  # wait for outflow-inflow>2
                self.pid_flow.setpoint(self.cfg.misc.start.flow.power.rate)
                await self.set_flow_pwm(self.cfg.misc.start.flow.power.pwm)

            elif run == Run.run:  # operation
                t_low = self.time
                self.pid_limit.reset()
                self.pid_load.reset()
                self.pid_pump.move_to(self.t_out, self.state.last_pwm, t=self.time)
                self.state.load_last = None

            elif run == Run.down:  # wait for outflow-inflow<2 for n seconds, cool down
                self.cp_flow = self.cfg.misc.stop.flow
                await self.cl.set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off)
                await self.cl.set(self.cfg.cmd.power, value=0)

            else:
                raise ValueError(f"State ?? {run !r}")

            orun = run
            self.state.run = int(run)

            # When de-icing starts, shut down (for now).
            if self.m_ice:
                if not m_ice:
                    m_ice = True
                    run = Run.off()
                    continue
            else:
                m_ice = False

            # Process the main switch

            if not self.cm_main or bool(self.m_errors):
                if cm_main:
                    cm_main = False
                    await self.cl.set(self.cfg.feedback.main, self.cm_main)
                    run = Run.off()
                    continue
            else:
                if not cm_main:
                    cm_main = True
                    await self.cl.set(self.cfg.feedback.main, self.cm_main)

            # Process the heating control switch

            if self.cm_heat != cm_heat:
                await self.cl.set(self.cfg.feedback.heat, self.cm_heat)
                cm_heat = self.cm_heat

            # Calculate desired temperatures

            # TODO handle switch-over water/heating correctly
            # we need three states:
            # - water only
            # - water while (water OR heating) is too low
            # - heating while water is sufficient

            t_max = self.c_water+self.cfg.adj.water
            t_min = self.c_water+self.cfg.adj.low.water
            t_cur = self.tb_water
            if cm_heat:
                t_max = max(t_max, self.c_heat+self.cfg.adj.heat)
                t_min = max(t_min, self.c_heat+self.cfg.adj.low.heat)
                t_cur = min(t_cur,self.tb_heat)
            t_max_out = min(self.cfg.adj.max, t_max+self.cfg.adj.more)


            # State handling

            if run == Run.off:  # nothing happens
                if not cm_main:
                    continue
                if bool(self.m_errors):
                    continue
                if self.force_on or t_cur < (t_min*2+t_max)/3:
                    # TODO configureable threshold?
                    run = Run.wait_time
                    self.force_on=False
                    continue

            elif run == Run.wait_time:  # wait for pump to be ready after doing whatever
                if self.state.get("t_load",0) + self.cfg.misc.start.delay < self.time:
                    run = Run.wait_flow
                    continue

            elif run == Run.wait_flow:  # wait for decent throughput
                if self.r_flow:
                    run = Run.flow
                    continue

            elif run == Run.flow:  # wait for decent throughput
                if self.r_flow >= self.cfg.misc.start.flow.init.rate*3/4:
                    run = Run.wait_power
                    continue
                l_flow = self.pid_flow(self.r_flow, t=self.time)
                print(f"Flow: {self.r_flow :.1f} : {l_flow :.3f}")
                await self.set_flow_pwm(l_flow)

            elif run == Run.wait_power:  # wait for pump to draw power
                if self.c_power >= self.cfg.misc.min_power:
                    run = Run.temp
                    continue
                l_flow = self.pid_flow(self.r_flow, t=self.time)
                print(f"Flow: {self.r_flow :.1f} : {l_flow :.3f} p={self.c_power :.1f}")
                await self.set_flow_pwm(l_flow)

            elif run == Run.temp:  # wait for outflow-inflow>2
                self.state.t_load = self.time
                if self.t_out-self.t_in > self.cfg.misc.start.delta:
                    run = Run.run
                    continue
                await self.handle_flow()

            elif run == Run.run:  # operation
                # see below for the main loop
                self.state.t_load = self.time

            elif run == Run.down:  # wait for outflow-inflow<2 for n seconds, cool down
                if self.m_ice:
                    # do not stop flow while de-icing
                    continue
                if self.t_out-self.t_in < self.cfg.misc.stop.delta:
                    run = Run.off
                    continue
                await self.handle_flow()

            else:
                raise ValueError(f"State ?? {run !r}")

            if run != Run.run:
                # If the incoming water is too cold, turn off heating
                # We DO NOT turn heating off while running: danger of overloading the heat pump
                # due to temperature jump, because the backflow is now fed by warm buffer
                # from the buffer instead of cold water returning from radiators,
                # esp. when they have been cooling off for some time

                heat_ok = min(self.tb_heat,self.t_out if self.state.last_pwm else 9999) >= self.c_heat
                if not heat_ok:
                    if self.state.heat_ok is not False:
                        self.state.heat_ok = False
                        await self.cl.set(self.cfg.setting.heat.mode.path, self.cfg.setting.heat.mode.off)

                continue
                # END not running

            # RUNNING ONLY after this point

            # if incoming water is no longer too cold, turn on heating
            heat_ok = min(self.tb_heat,self.t_out if self.state.last_pwm else 9999) >= self.c_heat
            if heat_ok:
                if self.state.heat_ok is True:
                    pass
                elif self.state.heat_ok is False:
                    self.state.heat_ok = self.time
                elif self.time-self.state.heat_ok > self.cfg.setting.heat.mode.delay:
                    await self.cl.set(self.cfg.setting.heat.mode.path, self.cfg.setting.heat.mode.on)
                    self.state.heat_ok = True
            else:
                # remember to wait
                self.state.heat_ok = self.time

            if self.c_power < self.cfg.misc.min_power:
                print(" NO POWER USE")
                run = Run.off
                continue

            if self.pid_load.state.get("setpoint",None) != t_max:
                logger.info("Load SET %.3f",t_max)
                self.pid_load.setpoint(t_max)

            if self.pid_limit.state.get("setpoint",None) != t_max_out:
                logger.info("Limit SET %.3f",t_max_out)
                self.pid_limit.setpoint(t_max_out)

            if self.pid_pump.state.get("setpoint",None) != t_max:
                logger.info("Pump SET %.3f",t_max)
                self.pid_pump.setpoint(t_max)
            
            # The pump rate is controlled by its intended output heat now
            if self.t_out>self.cfg.adj.max:
                l_pump=1
                # emergency handler
            else:
                l_pump = self.pid_pump(self.t_out, self.time)
                self.pid_flow.move_to(self.r_flow, l_pump, t=self.time)

            l_load = self.pid_load(t_cur, t=self.time)
            l_limit = self.pid_limit(self.t_out, t=self.time)
            lim=min(l_load,l_limit)
            self.pid_limit.move_to(self.t_out, lim, t=self.time)
            self.pid_load.move_to(t_cur, lim, t=self.time)

            tt = self.time
            if tt-tlast>5 or self.t_out>self.cfg.adj.max:
                tlast=tt
                print(f"t={int(tt)%1000:03d} cur={t_cur :.1f} t={self.t_out :.1f} Pump={l_pump :.3f} load={l_load :.3f}{'<' if l_load<l_limit else '>' if l_load>l_limit else '|'}{l_limit :.3f}")
            await self.set_load(lim)
            await self.set_flow_pwm(l_pump)
            self.state.load_last = lim

            if lim < self.cfg.lim.power.off and t_cur > t_min:
                if self.time-t_low > self.cfg.lim.power.time or self.tb_mid > (t_min*2+t_max)/3:
                    run=Run.off









            if True:
                pass

            elif run == 0: # off
                self.cp_flow = None
                await self.set_flow_pwm(0)
                await self.set_load(0)

            elif run == 1:
                # Startup A: start the load pump
                if "start_d" in self.state:
                    if self.time - self.state.start_d < self.cfg.misc.start.delay:
                        continue
                    self.cp_flow = self.cfg.misc.start.flow_init
                    self.pid_flow.reset()
                    self.state.last_pump = None
                    del self.state.start_d

                self.cp_flow = self.cfg.misc.start.flow_init
                if self.r_flow >= self.cfg.misc.start.flow*3/4:
                    run = 2
                    continue

            elif run == 2:
                # Startup B: get some power in until we have a delta
                await self.set_load(self.cfg.misc.start.power)
                if self.c_power < self.cfg.misc.min_power:
                    self.cp_flow = self.cfg.misc.start.flow_init
                    continue
                self.cp_flow = self.cfg.misc.start.flow

                # prime the controllers
                self.pid_pump.move_to(self.t_out, self.cfg.misc.start.flow_rate, t=self.time)
                self.pid_flow.move_to(self.cfg.misc.start.flow, self.cfg.misc.start.flow_rate, t=self.time)

                if self.t_out-self.t_in > self.cfg.misc.start.delta:
                    run = -1
                    continue



    async def _old_setup_flow(self):
        warned = False
        self.set_flow_pwm = set_pwm
        task_status.started()
        zero=False

        while True:
            await self.wait()
            if self.m_passthru is not False:
                await set_pwm(self.m_passthru)
                continue
            if self.cp_flow is None:
                if self.m_ice:
                    print("** ICE ERR PUMP **")
                continue

#           if self.t_out - self.t_in < 2 and not self.cp_heat:
#               port.ChangeDutyCycle(0)
#               continue

            r = self.cp_flow
            if r < self.cfg.lim.flow.min:
                await set_pwm(0)
                print("DUTY","OFF")
            else:
                if self.pid_flow.state.get("setpoint",None) != r:
                    logger.info("PUMP SET %.3f",r)
                    self.pid_flow.setpoint(r)
                warned = False

                if self.r_flow < self.cfg.lim.flow.min:
                    print(f"t={self.time%1000 :03.0f} in:0 want={r :.1f}")
                    zero=True
                    self.pid_flow.t0 = self.time
                    self.pid_pump.t0 = self.time

                    continue
                if zero:
                    zero=False

    async def handle_flow(self):
        """
        Flow handler while not operational
        """
        l_flow = self.pid_flow(self.r_flow, t=self.time)
        l_temp = self.pid_pump(self.t_out, t=self.time)
        print(f"t={self.time%1000 :03.0f} Pump={l_flow :.3f}/{l_temp :.3f} in:{self.r_flow :.1f}")
        res = max(l_flow,l_temp)
        self.pid_flow.move_to(self.r_flow, res, t=self.time)
        self.pid_pump.move_to(self.t_out, res, t=self.time)
        await self.set_flow_pwm(res)
        self.state.last_pump = res


    def has(self, name, value):
        setattr(self,name,value)
        if (evt := self._sigs.get(name)) is not None:
            evt.set()
        self.trigger()

    def trigger(self):
        if self.record:
            d=attrdict((k,v) for k,v in vars(self).items() if not k.startswith("_") and isinstance(v,(int,float,dict,tuple,list)))
            d.TS=self.time
            yprint(d, self.record)
            print("---",file=self.record)
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
                    if m.value == 30055:
                        print("WP COMM ERR")
                    elif m.path == P(":1"):
                        print("OOMPH?",m.value)
                    else:
                        errs[err] = m.value
                else:
                    errs.pop(err,None)
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
        """
        Wait for startup to be completed.

        Complain once per second about missing values, assuming there's a change.
        """
        while self._want:
            t = self.time
            print("Waiting",self._want)
            await self._got.wait()
            while (t2 := self.time)-t < 1:
                if not self._want:
                    break
                with anyio.move_on_after(t2-t):
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
                            self.trigger()

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
            run = Run(self.state.get("run",0))
            self.state.run = Run.down.value
            await self.save()

            await self.set_load(0)
            if self.t_out-self.t_in > self.cfg.misc.stop.delta:
                while self.t_out-self.t_in > self.cfg.misc.stop.delta:
                    await self.handle_flow()
                    await self.wait()

            tg.cancel_scope.cancel()

        await self.set_flow_pwm(0)
        self.state.run = 0
        await self.save()

    async def run(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        try:
            await self.run_pump(task_status=task_status)
        finally:
            print("*** OFF ***")
            with anyio.CancelScope(shield=True):
                await self.off()

    async def run_init(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        cfg = self._cfg
        async with anyio.create_task_group() as tg:
            await tg.start(self._kv, cfg.cmd.flow, "c_flow")
            await tg.start(self._kv, cfg.cmd.main, "cm_main")
            await tg.start(self._kv, cfg.cmd.heat, "cm_heat")
            await tg.start(self._kv, cfg.setting.heat.day, "c_heat")
            await tg.start(self._kv, cfg.setting.heat.night, "c_heat_night")
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
            await tg.start(self._kv, cfg.sensor.power, "c_power")

            try:
                with anyio.fail_after(self.cfg.misc.init_timeout):
                    await self.all_done()
            except TimeoutError:
                raise ValueError("missing:"+repr(self._want)) from None
            task_status.started()
            yprint({k:v for k,v in vars(self).items() if not k.startswith("_") and isinstance(v,(int,float,str))})

    async def run_rec(self, rec, tg, *, task_status=anyio.TASK_STATUS_IGNORED):
        task_status.started()
        t = None
        for r in yload(rec, multi=True):
            if r is None:
                print("END RECORDING")
                for _ in range(100):
                    await anyio.sleep(0.001)
                tg.cancel_scope.cancel()
                return
            self.__dict__.update(r)
            self.state = to_attrdict(self.state)
            self.trigger()
            for _ in range(20):
                await anyio.sleep(0.001)


    async def run_fake(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        async def fkv(var):
            while not hasattr(self,var):
                await self.wait()
        async with anyio.create_task_group() as tg:
            await fkv("c_flow")
            await fkv("cm_main")
            await fkv("cm_heat")
            await fkv("c_heat")
            await fkv("c_heat_night")
            await fkv("c_water")
            await fkv("m_passthru")
            await fkv("t_in")
            await fkv("t_out")
            await fkv("r_flow")
            await fkv("m_ice")
            await fkv("tb_water")
            await fkv("tb_heat")
            await fkv("tb_mid")
            await fkv("tb_low")
            await fkv("c_power")
            task_status.started()

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

class fake_cl:
    def __init__(self):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *tb):
        pass
    async def set(self,path,value,**k):
        print("SET",path,value)

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
@click.option("-r","--record",type=click.File("w"))
@click.option("-f","--force-on",is_flag=True)
async def run(obj,record,force_on):
    async with open_client(**mcfg.kv) as cl, anyio.create_task_group() as tg:
        d = Data(obj.cfg,cl, record=record)
        d.force_on=force_on

        await tg.start(d.run_init)
        await tg.start(d.err_mon)
        await tg.start(d.run)
        await tg.start(d.saver)


@main.command
@click.pass_obj
@click.argument("record",type=click.File("r"))
async def replay(obj,record):
    async with fake_cl() as cl, anyio.create_task_group() as tg:
        d = Data(obj.cfg,cl)
        await tg.start(d.run_rec, record, tg)
        await tg.start(d.run_fake)
        await tg.start(d.run)


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
    main(_anyio_backend="trio")
