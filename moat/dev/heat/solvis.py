from __future__ import annotations

"""
This program controls a SolvisMax+SolvisLea combination "manually"
because the SolvisMax controller doesn't support a heap of features I need.

See the accompanying .rst file for details.
"""


import asyncclick as click

from moat.util import (
    P,
    PathLongener,
    attrdict,
    combine_dict,
    pos2val,
    to_attrdict,
    val2pos,
    yload,
    yprint,
)
from moat.kv.client import open_client
from moat.lib.pid import CPID

import anyio
import io
import logging
import sys
import time
from enum import IntEnum, auto

FORMAT = "%(levelname)s %(pathname)-15s %(lineno)-4s %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT)

logger = logging.root

GPIO = None


class Run(IntEnum):
    "Pump controller state machine"

    # nothing happens
    off = 0
    # wait for pump to be ready after doing whatever
    wait_time = auto()
    # wait for throughput to show up
    wait_flow = auto()
    # wait for decent throughput
    flow = auto()
    # wait for pump to draw power
    wait_power = auto()
    # wait for outflow-inflow>2
    temp = auto()
    # operation
    run = auto()
    # ice
    ice = auto()
    # wait for outflow-inflow<2 for n seconds, cool down
    down = auto()


CFG = """
state: "/tmp/solvis.state"
adj:
    # offsets to destination temperature
    water: 3
    heat: 1.5
    more: 2  # output temperature offset
    max: 61  # don't try for more
    buffer: 1
    low:
        water: 1
        heat: .5
        buffer: -2
        factor: 0.4

        # threshold for heating. If pump PWM is zero, use buffer temperature.
        # If at least .pwm, use heat pump output.
        pwm: 0.8
    curve:
        dest: 21
        max: 75
        min: -15
        exp: 1.3
        current: !P temp.avg.temp.aussen_kompost.min
        setting: !P heat.s.heat.temp.cmd

        night:
            dest: 17
            start:
                wk: 5.5
                we: 7
            stop:
                wk: 21.5
                we: 23

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
    power: !P heat.s.pump.power  # m_power
    cop: !P home.ass.dyn.sensor.heizung.wp_cop.state  # m_cop
    temp:
        current: !P temp.avg.temp.aussen_kompost
        predict: !P temp.min.forecast:6
        pellet: !P heat.s.pellets.temp.top

setting:
    heat:
      day: !P heat.s.heat.temp        # c_heat
      night: !P heat.s.heat.temp_low  # c_heat_night
      power:
        pin: 19
      mode:
        path: !P heat.s.heat.mode.cmd    # 5:standby 2:auto 3:day 4:night
        on: 3
        off: 5
        delay: 30
        force:
          day:
            cmd: !P home.ass.dyn.switch.heizung.day_mode.cmd
            state: !P home.ass.dyn.switch.heizung.day_mode.state
          night:
            cmd: !P home.ass.dyn.switch.heizung.night_mode.cmd
            state: !P home.ass.dyn.switch.heizung.night_mode.state
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
    pellet:
      power: !P home.ass.dyn.switch.heizung.pellets.cmd
      temp: !P heat.s.pellets.temp.goal.cmd

feedback:
    main: !P home.ass.dyn.switch.heizung.wp.state
    heat: !P home.ass.dyn.switch.heizung.main.state
    ice: !P home.ass.dyn.binary_densor.heizung.wp_de_ice.state

misc:
    switch:
      state: !P heat.s.pump.switchover
    pellet:
        current: 1
        predict: 0.5

    init_timeout: 5
    de_ice:
      flow: 17  # desired flow rate when de-icing
      pwm: .5  # corresponding PWM output
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
        p: -0.05
        i: -0.0015
        d: 0.0
        tf: 0.0

        min: .2
        max: 1

        factor: 0
        offset: 0

        # state attr
        state: p_pump

    load:
        ## Primary heat exchanger control.
        ## We want the top buffer temperature to be at a certain value.
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

    buffer:
        ## More heat exchanger control. We want the bottom buffer temperature not to get too high.
        ##
        # setpoint: desired buffer temperature
        # input: buffer temperature
        # output: heat exchanger load
        ## Reduce the load as required to keep the buffer temperature down.
        p: 0.2
        i: 0.0001
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
        state: p_buffer

    limit:
        ## Secondary heat exchanger control. We don't want more load than the pump can transfer
        ## to the buffer, otherwise the system overheats.
        #
        # setpoint: desired buffer temperature plus adj.more
        # input: exchanger output temperature
        # output: heat exchanger load
        p: 0.05
        i: 0.001
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


with open("/etc/moat/moat.cfg", "r") as _f:
    mcfg = yload(_f, attr=True)

class APID(CPID):
    def __init__(self, data, name, cfg):
        super().__init__(cfg, data.state)
        self.data = data
        self.name = name

    async def setpoint(self, val):
        if self.state.get("setpoint", None) == val:
            return
        super().setpoint(val)

        try:
            await self.data.cl.set(self.cfg.log.setpoint, value=val, idem=True)
        except AttributeError:
            pass

    async def __call__(self, val, **kw):
        res = super().__call__(val, **kw)
        await self.log_value(res)
        return res

    async def log_value(self, res):

        if not isinstance(res,(int,float)):
            return
        try:
            await self.data.cl.set(self.cfg.log.value, value=res, idem=True)
        except AttributeError:
            pass


class Data:
    "encapsulates the heat supply system"

    force_on = False
    heat_dest = None

    def __init__(self, cfg, cl, record=None):
        self._cfg = cfg
        self._cl = cl
        self._got = anyio.Event()
        self._want = set()
        self._sigs = {}
        self.record = record
        self.pid = attrdict()

        try:
            with open(cfg.state) as sf:
                self.state = yload(sf, attr=True)
        except OSError:
            self.state = attrdict()

        # calculated pump flow rate, 0…1
        self.cp_flow = None
        self.m_errors = {}

        for k,v in self.cfg.pid.items():
            self.pid[k] = APID(self,k,v)

        self.state.setdefault("heat_ok", False)
        self.state.setdefault("pellet_on", None)

        try:
            path = self.cfg.output.flow.path
        except AttributeError:
            pin = self.cfg.output.flow.pin
            GPIO.setup(pin, GPIO.OUT)
            self._flow_port = port = GPIO.PWM(pin, 200)
            port.start(0)

            async def set_flow_pwm(r):
                self.state.last_pwm = r
                port.ChangeDutyCycle(100 * r)
        else:

            async def set_flow_pwm(r):
                self.state.last_pwm = r
                await self.cl.set(path, value=r, idem=True)

        self.set_flow_pwm = set_flow_pwm

    @property
    def time(self):
        "current time"
        try:
            return self.TS
        except AttributeError:
            return time.monotonic()

    @property
    def cl(self):
        "MoaT-KV controller"
        return self._cl

    @property
    def cfg(self):
        "config data"
        return self._cfg

    # async def set_flow_pwm(self, rate):
    # added by .run_flow

    def log_hc(self, i, *a):
        print("HC",i,*a, end="\r")
        sys.stdout.flush()

    async def log_zero(self):
        "log zero values for all PIDs"
        for pid in self.pid.values():
            await pid.log_value(0)

    async def set_load(self, p):
        "heat pump load update; sets to zero if less than minimum"
        if p < self.cfg.lim.power.min:
            await self.cl.set(self.cfg.cmd.power, value=0, idem=True)
            await self.cl.set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off, idem=True)
            self.state.last_load = 0
        else:
            await self.cl.set(self.cfg.cmd.power, value=min(p, 1), idem=True)
            await self.cl.set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.on, idem=True)
            self.state.last_load = p

    async def run_pump(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "Core method: Heat pump controller."
        cm_main = None
        run = Run(self.state.get("run", 0))
        # 0 off; 1 go_up, 2 up, 3 go_down
        # TODO charge the hot water part separately
        tlast = 0

        orun = None
        m_ice = False
        cm_main = None
        cm_heat = None
        n_cop = 0
        t_no_power = None
        heat_off = False
        water_ok = True
        heat_pin = self.cfg.setting.heat.get("power", {}).get("pin", None)
        if heat_pin is not None:
            GPIO.setup(heat_pin, GPIO.OUT)

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
            elif run == Run.off:
                pass
            elif run == Run.ice:
                pass
            elif run.value == orun.value + 1:
                pass
            elif orun != Run.off and run == Run.down:
                pass
            elif orun == Run.down and run == Run.off:
                pass
            else:
                raise ValueError(f"Cannot go from {orun.name} to {run.name}")

            # Handle state changes

            # redirect for shutdown
            if run == Run.off:
                if orun not in (Run.off, Run.wait_time, Run.wait_flow, Run.wait_power, Run.down):
                    run = Run.down

            # Report
            if orun != run:
                print(f"*** STATE: {run.name}")

            # Leaving a state
            if orun is None:  # fix stuff for startup
                # assume PIDs are restored from state
                # assume PWM is stable
                if run == Run.run:
                    last = self.state.get("load_last", None)
                    if last is not None:
                        await self.set_load(last)

            elif orun == run:  # no change
                pass

            elif orun == Run.down:
                pass

            oheat_off, heat_off = heat_off, None

            # Entering a state
            if orun == run:  # no change
                heat_off = oheat_off

                task_status.started()
                task_status = anyio.TASK_STATUS_IGNORED
                await self.wait()

            elif run == Run.off:  # nothing happens
                heat_off = False
                await self.set_flow_pwm(0)
                await self.set_load(0)
                self.state.last_pwm = None
                await self.log_zero()

            elif run == Run.wait_time:  # wait for the heat pump to be ready after doing whatever
                await self.set_flow_pwm(0)
                await self.set_load(0)
                await self.log_zero()

            elif run == Run.wait_flow:  # wait for flow
                heat_off = True
                await self.cl.set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off)
                await self.set_flow_pwm(self.cfg.misc.start.flow.init.pwm)

            elif run == Run.flow:  # wait for decent throughput
                pass

            elif run == Run.wait_power:  # wait for pump to draw power
                self.pid.flow.move_to(self.r_flow, self.state.last_pwm)
                await self.set_load(self.cfg.misc.start.power)

            elif run == Run.temp:  # wait for outflow-inflow>2
                await self.pid.flow.setpoint(self.cfg.misc.start.flow.power.rate)
                await self.set_flow_pwm(self.cfg.misc.start.flow.power.pwm)

            elif run == Run.run:  # operation

                heat_off = False
                self.state.setdefault("t_run", self.time)
                if orun is not None:
                    await self.log_zero()
                    self.pid.limit.reset()
                    self.pid.load.reset()
                    self.pid.buffer.reset()
                else:
                    await self.pid.flow.log_value(0)
                self.pid.pump.move_to(self.t_out, self.state.last_pwm, t=self.time)
                self.state.load_last = None

            elif run == Run.ice:  # wait for ice condition to stop
                await self.log_zero()

                heat_off = True
                await self.pid.flow.setpoint(self.cfg.misc.de_ice.flow)
                self.pid.flow.move_to(self.cfg.misc.de_ice.flow,self.cfg.misc.de_ice.pwm)

                await self.cl.set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off)
                await self.cl.set(self.cfg.cmd.power, value=0)

            elif run == Run.down:  # wait for outflow-inflow<2 for n seconds, cool down
                await self.log_zero()

                heat_off = True
                await self.pid.flow.setpoint(self.cfg.misc.stop.flow)
                await self.cl.set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off)
                await self.cl.set(self.cfg.cmd.power, value=0)

            else:
                raise ValueError(f"State ?? {run !r}")

            orun = run
            self.state.run = int(run)

            # When de-icing starts, shut down (for now).
            if self.m_ice:
                if not m_ice:
                    print("*** ICE ***")
                    m_ice = True
                    await self.cl.set(self.cfg.feedback.ice, True)
                    run = Run.ice
                    continue
            else:
                if m_ice:
                    await self.cl.set(self.cfg.feedback.ice, False)
                    print("*** NO ICE ***")
                m_ice = False

            # Process the main switch

            if not self.cm_main or bool(self.m_errors):
                if cm_main:
                    cm_main = False
                    await self.cl.set(self.cfg.feedback.main, self.cm_main)
                    print("OFF 7")
                    run = Run.off
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

            # TODO:

            # we need three states:
            # - water only
            # - water while (water OR heating) is too low  # TODO, needs switch
            # - heating while water is sufficient
            #
            # buffer temp < nominal: pump speed: deliver nominal+adj_low
            # buffer temp > nominal+adj: pump speed: deliver MAXTEMP
            # in between: interpolate

            # The system should be able to run in either steady-state or max-charge mode.

            tw_nom = self.c_water
            tw_low = tw_nom + self.cfg.adj.low.water
            tw_adj = tw_nom + self.cfg.adj.water

            th_nom = self.c_heat
            th_low = th_nom + self.cfg.adj.low.heat
            th_adj = th_nom + self.cfg.adj.heat

            ## TODO add an output to switch the supply
            if True:
                pass
            elif self.tb_water < tw_low:
                water_ok = False
            elif self.tb_water >= tw_adj and self.tb_heat >= tw_low:
                water_ok = True

            if cm_heat and water_ok:
                t_nom = max(th_nom, tw_nom)
                t_low = max(th_low, tw_low)
                t_adj = max(th_adj, tw_adj)

                t_cur = self.tb_heat
            else:
                t_nom = tw_nom
                t_low = tw_low
                t_adj = tw_adj

                t_cur = self.tb_water

            # PID controller settings
            f = val2pos(t_nom, t_cur, t_adj, clamp=True)
            t_limit = min(self.cfg.adj.max, t_adj + self.cfg.adj.more)
            if self.tb_heat < t_low:
                t_limit += (t_low-self.tb_heat) * self.cfg.adj.low.factor
            t_pump = pos2val(t_low, f, t_limit + 0.2 * (t_low - t_limit))
            t_load = t_adj + self.cfg.adj.buffer
            t_buffer = t_low + self.cfg.adj.low.buffer  # <0

            # on/off thresholds
            t_set_on = (t_low + t_adj) / 2  # top
            t_set_off = t_nom

            # State handling

            if run == Run.off:  # nothing happens
                if self.state.pellet_on:
                    r = "pell"
                if not cm_main:
                    r = "main"
                elif bool(self.m_errors):
                    r = "errn"
                elif self.force_on or t_cur < t_set_on:
                    # TODO configureable threshold?
                    run = Run.wait_time
                    self.force_on = False
                    continue
                else:
                    r = "temp"
                print(f"      -{r} cur={t_cur :.1f} on={t_set_on :.1f}", end="\r")
                sys.stdout.flush()

            elif run == Run.wait_time:  # wait for pump to be ready after doing whatever
                if self.state.get("t_load", 0) + self.cfg.misc.start.delay < self.time:
                    run = Run.wait_flow
                    continue

            elif run == Run.wait_flow:  # wait for decent throughput
                if self.r_flow:
                    run = Run.flow
                    continue

            elif run == Run.flow:  # wait for decent throughput
                if self.r_flow >= self.cfg.misc.start.flow.init.rate * 3 / 4:
                    run = Run.wait_power
                    continue
                l_flow = await self.pid.flow(self.r_flow, t=self.time)
                print(f"Flow: {self.r_flow :.1f} : {l_flow :.3f}")
                await self.set_flow_pwm(l_flow)

            elif run == Run.wait_power:  # wait for pump to draw power
                if self.m_power >= self.cfg.misc.min_power:
                    run = Run.temp
                    continue
                l_flow = await self.pid.flow(self.r_flow, t=self.time)
                print(f"Flow: {self.r_flow :.1f} : {l_flow :.3f} p={self.m_power :.1f}")
                await self.set_flow_pwm(l_flow)

            elif run == Run.temp:  # wait for outflow-inflow>2
                self.state.t_load = self.time
                if self.t_out - self.t_in > self.cfg.misc.start.delta:
                    run = Run.run
                    continue
                await self.handle_flow()

            elif run == Run.run:  # operation
                # see below for the main loop
                self.state.t_load = self.time

            elif run == Run.ice:  # no operation
                await self.handle_flow()
                if not self.m_ice:
                    run = Run.down
                    continue

            elif run == Run.down:  # wait for outflow-inflow<2 for n seconds, cool down
                await self.handle_flow()
                if self.t_out - self.t_in < self.cfg.misc.stop.delta:
                    print("OFF 1",self.t_out, self.t_in)
                    run = Run.off
                    continue

            else:
                raise ValueError(f"State ?? {run !r}")

            heat_ok = (
                run in {Run.off, Run.wait_time, Run.run, Run.down}
                and (not heat_off)
                and (self.tb_heat if self.m_switch else pos2val(self.tb_heat, (self.state.last_pwm or 0)/self.cfg.adj.low.pwm, self.t_out, clamp=True)) >= self.c_heat
            )
            if not heat_ok:
                # If the incoming water is too cold, turn off heating
                # We DO NOT turn heating off while running: danger of overloading the heat pump
                # due to temperature jump, because the backflow is now fed by warm buffer
                # from the buffer instead of cold water returning from radiators,
                # esp. when they have been cooling off for some time
                if run != Run.run and self.state.heat_ok is not False:
                    self.log_hc(1)
                    if heat_pin is None:
                        await self.cl.set(
                            self.cfg.setting.heat.mode.path,
                            self.cfg.setting.heat.mode.off,
                        )
                    else:
                        GPIO.output(heat_pin, False)
                    self.state.heat_ok = False
                else:
                    self.log_hc(2)
            elif self.state.heat_ok is True:
                self.log_hc(3)
            elif self.state.heat_ok is False:
                self.log_hc(4)
                self.state.heat_ok = self.time
            elif self.time - self.state.heat_ok > self.cfg.setting.heat.mode.delay:
                self.log_hc(5)
                if heat_pin is None:
                    await self.cl.set(
                        self.cfg.setting.heat.mode.path,
                        self.cfg.setting.heat.mode.on,
                    )
                else:
                    GPIO.output(heat_pin, True)
                self.state.heat_ok = True
            else:
                # wait
                self.log_hc(6)

            # turn off if the pellet burner is warm
            if self.state.pellet_on and self.heat_dest <= self.m_pellet - 1:
                print("OFF 2",self.heat_dest, self.m_pellet)
                run = Run.off
                continue

            if run != Run.run:
                continue
                # END not running

            # RUNNING ONLY after this point

            if self.m_power < self.cfg.misc.min_power:
                # might be ice or whatever, so wait
                if t_no_power is None:
                    t_no_power = self.time
                elif self.time - t_no_power > 20:
                    print("OFF 3 NO POWER USE")
                    run = Run.off
                    continue
            else:
                t_no_power = None

            await self.pid.load.setpoint(t_load)
            await self.pid.buffer.setpoint(t_buffer)
            await self.pid.limit.setpoint(t_limit)
            await self.pid.pump.setpoint(t_pump)

            # The pump rate is controlled by its intended output heat now
            if self.t_out > self.cfg.adj.max:
                l_pump = 1
                # emergency handler
            else:
                l_pump = await self.pid.pump(self.t_out, t=self.time)
                # self.pid.flow.move_to(self.r_flow, l_pump, t=self.time)

            l_load = await self.pid.load(t_cur, t=self.time)
            l_buffer = await self.pid.buffer(self.tb_low, t=self.time)
            l_limit = await self.pid.limit(self.t_out, t=self.time)
            lim = min(l_load, l_buffer, l_limit)

            tt = self.time
            if tt - tlast > 5 or self.t_out > self.cfg.adj.max:
                tlast = tt
                pr = (
                    f"t={int(tt)%1000:03d}",
                    f"buf={t_cur :.1f}/{self.tb_mid :.1f}/{self.tb_low :.1f}",
                    f"t={self.t_out :.1f}/{self.t_in :.1f}",
                    f"Pump={l_pump :.3f}",
                    f"load{'=' if lim == l_load else '_'}{l_load :.3f}",
                    f"buf{'=' if lim == l_buffer else '_'}{l_buffer :.3f}",
                    f"lim{'=' if lim == l_limit else '_'}{l_limit :.3f}",
                )
                print(*pr)
            await self.set_load(lim)
            await self.set_flow_pwm(l_pump)
            self.state.load_last = lim

            # COP
            if self.m_power:
                cop = 1.16 * 60 * self.r_flow * (self.t_out - self.t_in) / 1000 / self.m_power
                self.m_cop += 0.0001 * self.m_power * (cop - self.m_cop)
                if n_cop <= 0:
                    n_cop = 100
                    await self.cl.set(self.cfg.sensor.cop, self.m_cop)
                else:
                    n_cop -= 1

            # Finally, we might want to turn the heat exchanger off.

            # Buffer head temperature high enough?
            if t_cur >= t_adj:
                # Running long enough or temperature *really* high?
                if (
                    self.time - self.state.t_run > self.cfg.lim.power.time
                    and self.tb_mid >= t_set_off
                ):
                    print("OFF 4",t_cur,t_adj,self.tb_mid,t_set_off)
                    run = Run.off
                    continue
                elif self.tb_low >= t_low:
                    print("OFF 5",t_cur,t_adj,self.tb_low,self.t_low)
                    run = Run.off
                    continue

    async def run_set_pellet(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """run the pellet burner when it's too cold for the heat pump"""
        run = self.state.pellet_on
        if run is not None:
            await self._cl.set(self.cfg.cmd.pellet.power, run)
        task_status.started()

        while True:
            for _ in range(100):
                await self.wait()

            if (
                self.m_air < self.cfg.misc.pellet.current
                and self.m_air_pred < self.cfg.misc.pellet.predict
            ):
                if run is True:
                    continue
                run = True
            elif (
                self.m_air > self.cfg.misc.pellet.current
                and self.m_air_pred > self.cfg.misc.pellet.predict
            ):
                if run is False:
                    continue
                run = False
            else:
                continue

            await self._cl.set(self.cfg.cmd.pellet.power, run)
            if run and self.heat_dest is not None:
                await self._cl.set(
                    self.cfg.cmd.pellet.temp,
                    round(self.heat_dest + 0.8, 1),
                    idem=True,
                )
            self.state.pellet_on = run

    async def run_set_heat(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """set the goal for heating"""
        lock_day = False

        cf = self.cfg.adj.curve

        def vt(tau, ti):
            return ti + (cf.max - ti) * pow((ti - tau) / (ti - cf.min), 1 / cf.exp)

        locks = attrdict(day=False, night=False)
        dest = cf.dest
        t_cur = None
        _lock = anyio.Lock()

        async def _upd():
            nonlocal cf, dest, locks, t_cur, _lock
            async with _lock:
                import datetime

                dt = datetime.datetime.now()
                s1 = cf.night.start.wk if dt.weekday() < 5 else cf.night.start.we  # 5=sat
                h = dt.hour + dt.minute / 60
                if h < s1:
                    dest = cf.night.dest
                    delay = (s1 - h) * 60
                else:
                    s2 = (
                        cf.night.stop.wk if dt.weekday() not in (4, 5) else cf.night.stop.we
                    )  # 5=sat
                    if h < s2:
                        dest = cf.dest
                        delay = (s2 - h) * 60
                    else:
                        dest = cf.night.dest
                        delay = (24 - h) * 60

                if locks.day:
                    dest = cf.dest
                elif locks.night:
                    dest = cf.night.dest

                ht = vt(t_cur, dest)
                logger.debug("HZ: %.1f %.1f", ht, t_cur)
                await self._cl.set(cf.setting, int(ht + 0.8), idem=True)
                self.heat_dest = ht
                if self.state.pellet_on:
                    await self._cl.set(
                        self.cfg.cmd.pellet.temp,
                        round(ht + 0.8, 1),
                        idem=True,
                    )

                return delay

        async def sf_day_night(sf, dn, nd, *, task_status):
            async with self._cl.watch(sf[dn].cmd, max_depth=0, fetch=True) as msgs:
                task_status.started()
                async for m in msgs:
                    try:
                        val = m.value
                    except AttributeError:
                        continue
                    await self._cl.set(sf[dn].state, val)
                    if val:
                        await self._cl.set(sf[nd].cmd, False, idem=True)
                        await self._cl.set(sf[nd].state, False, idem=True)
                        locks[nd] = False
                    locks[dn] = val
                    await _upd()

        async def update_dest(*, task_status):
            nonlocal lock_day, t_cur
            d = await _upd()
            task_status.started()
            while True:
                await anyio.sleep(d + 10)
                d = await _upd()

        async with (
            anyio.create_task_group() as tg,
            self._cl.watch(cf.current, max_depth=0, fetch=True) as msgs,
        ):
            sf = self.cfg.setting.heat.mode.force
            task_status.started()
            async for m in msgs:
                if "value" not in m:
                    if m.get("state", "") == "uptodate":
                        await tg.start(update_dest)
                        await tg.start(sf_day_night, sf, "day", "night")
                        await tg.start(sf_day_night, sf, "night", "day")
                    else:
                        continue
                elif t_cur is None:
                    t_cur = m.value
                    continue
                else:
                    t_cur = m.value
                await _upd()

    async def handle_flow(self):
        """
        Flow handler while not operational
        """
        l_flow = await self.pid.flow(self.r_flow, t=self.time)
        l_temp = await self.pid.pump(self.t_out, t=self.time)
        print(
            f"t={self.time%1000 :03.0f}",
            f"Pump:{l_flow :.3f}/{l_temp :.3f}",
            f"flow={self.r_flow :.1f}",
            f"t={self.t_out :.1f}",
        )
        res = max(l_flow, l_temp)
        # self.pid.flow.move_to(self.r_flow, res, t=self.time)
        # self.pid.pump.move_to(self.t_out, res, t=self.time)
        await self.set_flow_pwm(res)
        self.state.last_pump = res

    def has(self, name, value):
        "Update a variable."
        setattr(self, name, value)
        if (evt := self._sigs.get(name)) is not None:
            evt.set()
        self.trigger()

    def trigger(self):
        "Signal that some variable has been updated."
        if self.record:
            d = attrdict(
                (k, v)
                for k, v in vars(self).items()
                if not k.startswith("_") and isinstance(v, (int, float, dict, tuple, list))
            )
            d.TS = self.time
            yprint(d, self.record)
            print("---", file=self.record)
        self._got.set()
        self._got = anyio.Event()

    async def err_mon(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "Monitor the heat pump for errors"
        async with self.cl.watch(self.cfg.sensor.error, long_path=False, fetch=True) as msgs:
            task_status.started()
            errs = self.m_errors
            err_base = P("pump")
            pl = PathLongener(())
            async for m in msgs:
                if "value" not in m:
                    continue
                pl(m)
                err = err_base + m.path
                was = bool(errs)
                if m.value:
                    if m.value == 30055:
                        print("WP COMM ERR")
                    elif m.path == P(":1"):
                        print("ERROR", m.value)
                    else:
                        print("ERROR", m.path, m.value)
                        errs[err] = m.value
                else:
                    errs.pop(err, None)
                if was or errs:
                    print("****** ERROR ********", errs)
                self.trigger()

    async def wait(self):
        "wait for update to any variable"
        await self._got.wait()

    async def wait_for(self, v):
        "wait for update to a specific variable"
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
            print("Waiting", self._want)
            await self._got.wait()
            while (t2 := self.time) - t < 1:
                if not self._want:
                    break
                with anyio.move_on_after(t2 - t):
                    await self._got.wait()

    async def _kv(self, p, v, *, task_status=anyio.TASK_STATUS_IGNORED):
        self._want.add(v)
        miss = False
        task_status.started()
        async with self._cl.watch(p, max_depth=0, fetch=True) as msgs:
            async for m in msgs:
                if m.get("state", "") == "uptodate":
                    if hasattr(self, v):
                        miss = False
                        self._want.remove(v)
                        if not self._want:
                            self.trigger()

                    else:
                        logger.warning("Missing: %r:%r", p, v)
                        miss = True
                elif "value" not in m:
                    logger.warning("Unknown: %r:%r: %r", p, v, m)
                else:
                    logger.debug("Value: %r:%r", p, m.value)
                    if miss:
                        miss = False
                        self._want.remove(v)
                    self.has(v, m.value)

    async def off(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "turn the heat pump off in a controlled way"
        self.state.run = Run.down.value
        await self.save()

        await self.set_load(0)
        task_status.started()
        if self.t_out - self.t_in > self.cfg.misc.stop.delta:
            while self.t_out - self.t_in > self.cfg.misc.stop.delta:
                await self.handle_flow()
                await self.wait()

        await self.set_flow_pwm(0)
        self.state.run = 0
        await self.save()

    async def run(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        main runner. Wraps `run_pump`
        but turns the heat pump off on exit/error.
        """
        try:
            await self.run_pump(task_status=task_status)
        except BaseException as exc:
            e = exc
        else:
            e = None
        finally:
            print(f"*** OFF {e !r} ***")
            with anyio.CancelScope(shield=True):
                await self.off()

    async def run_init(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "setup listeners"
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
            await tg.start(self._kv, cfg.sensor.cop, "m_cop")
            await tg.start(self._kv, cfg.sensor.buffer.top, "tb_water")
            await tg.start(self._kv, cfg.sensor.buffer.heat, "tb_heat")
            await tg.start(self._kv, cfg.sensor.buffer.mid, "tb_mid")
            await tg.start(self._kv, cfg.sensor.buffer.low, "tb_low")
            await tg.start(self._kv, cfg.sensor.power, "m_power")
            await tg.start(self._kv, cfg.sensor.temp.current, "m_air")
            await tg.start(self._kv, cfg.sensor.temp.predict, "m_air_pred")
            await tg.start(self._kv, cfg.sensor.temp.pellet, "m_pellet")
            await tg.start(self._kv, cfg.misc.switch.state, "m_switch")

            try:
                with anyio.fail_after(self.cfg.misc.init_timeout):
                    await self.all_done()
            except TimeoutError:
                raise ValueError("missing:" + repr(self._want)) from None
            task_status.started()
            yprint(
                {
                    k: v
                    for k, v in vars(self).items()
                    if not k.startswith("_") and isinstance(v, (int, float, str))
                },
            )

    async def run_rec(self, rec, tg, *, task_status=anyio.TASK_STATUS_IGNORED):
        "read a recording"
        task_status.started()
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
        "run a playback"

        async def fkv(var):
            while not hasattr(self, var):
                await self.wait()

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
        await fkv("m_cop")
        await fkv("tb_water")
        await fkv("tb_heat")
        await fkv("tb_mid")
        await fkv("tb_low")
        await fkv("m_power")
        await fkv("m_air")
        await fkv("m_air_pred")
        await fkv("m_pellet")
        await fkv("m_switch")
        task_status.started()

    async def saver(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "loop to periodically save the current state"
        task_status.started()
        while True:
            await anyio.sleep(10)
            await self.save()
            await self.wait()

    async def save(self):
        "save the current state"
        logger.debug("Saving")
        f = anyio.Path(self.cfg.state)
        fn = anyio.Path(self.cfg.state + ".n")
        fs = io.StringIO()
        yprint(self.state, fs)
        await fn.write_text(fs.getvalue())
        await fn.rename(f)


class fake_cl:
    "fake MoaT-KW client, for playbacks"

    def __init__(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    async def set(self, path, value, **_k):
        # noqa:D102
        print("SET", path, value)


# GPIO.setup(12, GPIO.OUT)
#
# p = GPIO.PWM(12, .2)  # frequency=50Hz
# p.start(50)
# try:
#    while 1:
#        time.sleep(10)
# except KeyboardInterrupt:
#    p.stop()
#    GPIO.cleanup()


@click.group
@click.pass_context
@click.option("-c", "--config", type=click.File("r"), help="config file")
async def cli(ctx, config):
    """
    Manage a Solvis heat pump controller

    Given a SolvisLea heat pump (and another, modbus-controllable,
    source of heat), teach it to behave.
    """
    ctx.obj = attrdict()
    cfg = yload(CFG, attr=True)
    if config is not None:
        cfg = combine_dict(yload(config, attr=True), cfg, cls=attrdict)
    ctx.obj.cfg = cfg

    global GPIO
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        pass
    else:
        GPIO.setmode(GPIO.BCM)


@cli.command
@click.pass_obj
@click.option("-r", "--record", type=click.File("w"))
@click.option("-f", "--force-on", is_flag=True)
async def run(obj, record, force_on):
    "Heat pump controller. Designed to run continuously"
    async with open_client(**mcfg.kv) as cl, anyio.create_task_group() as tg:
        d = Data(obj.cfg, cl, record=record)
        d.force_on = force_on

        await tg.start(d.run_init)
        await tg.start(d.err_mon)
        await tg.start(d.run_set_heat)
        await tg.start(d.run_set_pellet)
        await tg.start(d.saver)
        await d.run()


@cli.command
@click.pass_obj
@click.argument("record", type=click.File("r"))
async def replay(obj, record):
    "Replay a previous run, for testing"
    async with fake_cl() as cl, anyio.create_task_group() as tg:
        d = Data(obj.cfg, cl)
        await tg.start(d.run_rec, record, tg)
        await tg.start(d.run_fake)
        await tg.start(d.run)


@cli.command
@click.pass_obj
async def pwm(obj):
    """
    Run a backgrounds task for software PWM outputs.

    This keeps the PWM alive if/when "… solvis run" is restarted.
    """
    async with open_client(**mcfg.kv) as cl, anyio.create_task_group() as tg:
        for k, p in obj.cfg.output.items():
            tg.start_soon(_run_pwm, cl, k, p)


async def _run_pwm(cl, k, v):
    GPIO.setup(v.pin, GPIO.OUT)
    port = GPIO.PWM(v.pin, v.get("freq", 200))
    port.start(0)
    async with cl.watch(v.path, max_depth=0, fetch=True) as msgs:
        async for m in msgs:
            if m.get("state", "") == "uptodate":
                pass
            elif "value" not in m:
                logger.warning("Unknown: %s:%r: %r", k, v, m)
            else:
                logger.info("Value: %s:%r", k, m.value)
                port.ChangeDutyCycle(100 * m.value)


@cli.command
@click.pass_obj
async def off(obj):
    "Emergency handler to turn the heat pump off in a controlled way."
    async with open_client(**mcfg.kv) as cl, anyio.create_task_group() as tg:
        d = Data(obj.cfg, cl)
        await tg.start(d.run_init)
        await d.off()
        tg.cancel_scope.cancel()


@cli.command
@click.pass_obj
async def curve(obj):
    "show the current heating curve"
    from math import pow

    cf = obj.cfg.adj.curve

    def vt(tau, ti):
        return ti + (cf.max - ti) * pow((ti - tau) / (ti - cf.min), 1 / cf.exp)

    for t in range(cf.min, cf.night.dest):
        print(f"{t :3d} {vt(t,cf.dest) :.1f} {vt(t,cf.night.dest) :.1f}")
