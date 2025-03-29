"""
This program controls a SolvisMax+SolvisLea combination "manually"
because the SolvisMax controller doesn't support a heap of features I need.

See the accompanying .rst file for details.
"""

from __future__ import annotations

import anyio
import io
import logging
import sys
import time
import subprocess
from enum import IntEnum, auto

import asyncclick as click
import aionotify

from moat.util import (
    P,
    Path,
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
import contextlib

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
    max_max: 62  # don't try for more
    max_pellet: 75
    buffer: 1
    pellet:
      pid:
        load:
          d: 0
          tf: 0
      load: 2
      low: 10
      preload:
        low: 1.5  # PID controller
        wp: 0.5  # PID controller
      max: 75
      startup:
        buf: 5  # add to max buffer temp
        patch:
          path:
          - !P heat.s.pellets.aux:1.goal
          - !P heat.s.pellets.aux:2.goal
          - !P heat.s.pellets.aux.r-min.goal
          stop: 65
    low:
        water: 1
        heat: .5
        buffer: -2
        factor: 0.4

        # threshold for heating. If pump PWM is zero, use buffer temperature.
        # If at least .pwm, use heat pump output.
        # Also adjust the target by pre_heat.
        pwm: 0.7
        pre_heat: -1
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
        inverted: false
        override:
            flag: !P home.ass.state.input_boolean.test_override_on.state
            val: !P home.ass.state.input_number.test_override_pct.state
sensor:
    pump:
        in: !P heat.s.pump.temp.in   # t_in
        out: !P heat.s.pump.temp.out # t_out
        flow: !P heat.s.pump.flow    # r_flow: flow rate
        ice: !P heat.s.pump.de_ice   # m_ice
        state: !P heat.s.pump.state
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
        heat: !P heat.s.heating.temp.out
    pellet:
      state: !P heat.s.pellets.state

setting:
    heat:
      day: !P heat.s.heat.temp        # c_heat
      night: !P heat.s.heat.temp_low  # c_heat_night
#     power:
#       pin: 19
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

lim:
    pellet:
      t_min: 10000  # run approx 3h minimum
      stop:
        buffer: -1
      start:
        buffer: 8  # start WP if buffer is too far below
        heat:
          delta: 1.5  #
          scale: .1
      temp:
        min: 60  # ask at least for this temperature
    times:
       start: 200
       ice: 900
       stop: 100
    power:
        min: .04
        off: .2   # power cutoff if the buffer is warm enough
        time: 300  # must run at least this long
    start: 50
    defrost:
        temp: 7  # run pump when below that
        flow: 5  # don't need much
    idle: 25  # don't run pump when below that
    low:
        # when we switch off: If the decaying average of the heat pump limiter with "scale"
        # goes below "limit"
        scale: .01
        limit: .1
        pellet:
          scale: .01
          limit: .4

cmd:
    bypass:
      cmd: !P home.ass.dyn.switch.heizung.wp_bypass.cmd  # c_bypass
      mode: !P heat.s.pump.cmd.want.mode
      power: !P heat.s.pump.cmd.want.power
    flow: !P heat.s.pump.rate.cmd       # c_flow
    wp: !P home.ass.dyn.switch.heizung.wp.cmd  # cm_wp
    heat: !P home.ass.dyn.switch.heizung.main.cmd  # cm_heat
    mode:
      path: !P heat.s.pump.cmd.mode       # write
      on: 3
      off: 0
    power: !P heat.s.pump.cmd.power
    pellet:
      force: !P heat.s.pellets.load.force  # cm_pellet_force
      temp: !P heat.s.pellets.temp.goal.cmd
      load: !P heat.s.pellets.load.goal.cmd
      wanted: !P heat.s.pellets.power.cmd.auto  # set by us when requesting
      run: !P heat.s.pellets.power.cmd  # cm_pellet - set by MoaT-VK, also controls the burner

    passthru:
      pump: !P home.ass.dyn.switch.heizung.wp_auto_mode.cmd       # m_passthru_pump
      pellet: !P home.ass.dyn.switch.heizung.pellet_auto_mode.cmd     # m_passthru_pellet

feedback:
    wp: !P home.ass.dyn.switch.heizung.wp.state
    bypass: !P home.ass.dyn.switch.heizung.wp_bypass.state
    main: !P home.ass.dyn.switch.heizung.wp.state
    heat: !P home.ass.dyn.switch.heizung.main.state
    pump: !P home.ass.dyn.binary_sensor.heizung.pump.state
    ice: !P home.ass.dyn.binary_sensor.heizung.wp_de_ice.state
#   pellet: !P home.ass.dyn.binary_sensor.heizung.pellets.state
    passthru:
      pump: !P home.ass.dyn.switch.heizung.wp_auto_mode.state
      pellet: !P home.ass.dyn.switch.heizung.pellet_auto_mode.state

misc:
    switch:
      state: !P heat.s.pump.switchover
      # flag: heat pump feeds the water, not the heating
    pellet:
        current: 1
        predict: 0.5
        avg_off: 0

    init_timeout: 5
    de_ice:
      flow: 17  # desired flow rate when de-icing
      pwm: .5  # corresponding PWM output
      min: .3  # minimum PWM
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
    heat:
      delta: 10
      # if buffer_low+delta is > t_adj then run the heating pump
#   mon_solvis:
#     err: !P heat.s.control.errors
#     data: "/etc/moat/modbus.stiebelfake.yaml"
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

    p_load:
        ## Primary pellet control.
        ## We want the top buffer temperature to be at a certain value.
        ##
        # setpoint: desired buffer temperature
        # input: buffer temperature
        # output: heat exchanger load
        ## Add as much load as required to keep the buffer temperature up.
        p: 0.01
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
        state: pp_load

    p_buffer:
        ## More pellet control. We want the bottom buffer temperature not to get too high.
        ##
        # setpoint: desired buffer temperature
        # input: buffer temperature
        # output: heat exchanger load
        ## Reduce the load as required to keep the buffer temperature down.
        p: 0.1
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
        state: pp_buffer

"""


with open("/etc/moat/moat.cfg") as _f:
    mcfg = yload(_f, attr=True)


class APID(CPID):
    "a PID that logs asynchronously"

    def __init__(self, data, name, cfg):
        super().__init__(cfg, data.state)
        self.data = data
        self.name = name

    async def setpoint(self, val):
        "communicates the setpoint"
        if self.state.get("setpoint", None) == val:
            return
        super().setpoint(val)

        with contextlib.suppress(AttributeError):
            await self.data.cl.set(self.cfg.log.setpoint, value=val, idem=True)

    async def __call__(self, val, **kw):
        "run the PID and log the result"
        res = super().__call__(val, **kw)
        await self.log_value(res[0] if isinstance(res, tuple) else res)
        return res

    async def log_value(self, res):
        "log the result"
        if not isinstance(res, (int, float)):
            return
        with contextlib.suppress(AttributeError):
            await self.data.cl.set(self.cfg.log.value, value=res, idem=True)


class Data:
    "encapsulates the heat supply system"

    force_on = False
    heat_dest = None

    t_adj = None
    t_nom = None
    t_low = None
    t_limit = None
    wp_on = False
    hc_pos = 0
    r_no = "----"
    pellet_load = 0
    pellet_on: bool = None

    # outside temperature average
    t_ext_avg = None

    def __init__(self, cfg, cl, record=None, no_op=False, state=None):
        self._cfg = cfg
        self._cl = cl
        self._got = anyio.Event()
        self._want = set()
        self._sigs = {}
        self.record = record
        self.pid = attrdict()
        self.no_op = no_op

        self.state = state or attrdict()

        # calculated pump flow rate, 0…1
        self.cp_flow = None
        self.m_errors = {}

        for k, v in self.cfg.pid.items():
            self.pid[k] = APID(self, k, v)

        self.state.setdefault("heat_ok", False)
        self.state.setdefault("t_pellet_on", None)
        self.state.setdefault("start_p", False)

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
                await self.cl_set(path, value=r, idem=True)

        self.set_flow_pwm = set_flow_pwm

    async def reload_cfg(self, cfgf, *, task_status=anyio.TASK_STATUS_IGNORED):
        flg = aionotify.Flags.CLOSE_WRITE | aionotify.Flags.MOVE_SELF
        async with aionotify.Watcher() as watcher:
            await watcher.awatch(path=cfgf, flags=flg)
            task_status.started()
            async for _evt in watcher:
                while True:
                    with anyio.move_on_after(2):
                        await watcher.get_event()
                        continue
                    break
                print("*** RELOADING ***")
                with open(cfgf, "r") as cff:
                    self._cfg = combine_dict(yload(cff, attr=True), self.cfg, cls=attrdict)

        pass

    @property
    def time(self):
        "current time"
        try:
            return self.TS
        except AttributeError:
            return time.time()

    @property
    def cl(self):
        "MoaT-KV controller"
        return self._cl

    async def cl_set(self, *a, **kw):
        "just calls self.cl.set(), except when running with ``--no-save``"
        if self.no_op:
            print("SET", a, kw)
            return
        return await self._cl.set(*a, **kw)

    @property
    def cfg(self):
        "config data"
        return self._cfg

    # async def set_flow_pwm(self, rate):
    # added by .run_flow

    def log_hc(self, i, *a):
        "print+remember the current heating state cause"
        print(f" H={i}", *a, end="\r" if self.hc_pos == i else "\n")
        sys.stdout.flush()
        self.hc_pos = i

    async def log_zero(self):
        "log zero values for all PIDs"
        for name, pid in self.pid.items():
            if name.startswith("p_"):
                continue
            await pid.log_value(0)

    async def set_load(self, p):
        "heat pump load update; sets to zero if less than minimum"
        if p < self.cfg.lim.power.min:
            await self.cl_set(self.cfg.cmd.power, value=0, idem=True)
            await self.cl_set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off, idem=True)
            self.state.last_load = 0
        else:
            await self.cl_set(self.cfg.cmd.power, value=min(p, 1), idem=True)
            await self.cl_set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.on, idem=True)
            self.state.last_load = p

    async def run_pump(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "Core method: Heat pump controller."
        run = Run(self.state.get("run", 0))
        # 0 off; 1 go_up, 2 up, 3 go_down
        # TODO charge the hot water part separately
        tlast = 0

        orun = None
        m_ice = False
        cm_wp = None
        cm_heat = None
        n_cop = 0
        t_no_power = None
        heat_off = False
        water_ok = True
        t_change_max = None
        heat_pin = self.cfg.setting.heat.get("power", {}).get("pin", None)

        self.state.setdefault("avg_heat", self.t_heat)
        self.state.pop("avg_heat_d", 0)
        self.state.setdefault("avg_heat_t", 0)
        self.state.setdefault("t_change", None)

        if heat_pin is not None:
            GPIO.setup(heat_pin, GPIO.OUT)

        if self.heat_dest is None:
            print("wait heat_dest")
            while self.heat_dest is None:
                await self.wait()
            print("OK")

        while True:
            #
            # Part 1: what to do when a state changes
            #
            # check for inappropriate state changes
            #
            if self.c_bypass:
                print("*** BYPASS ON ***")
                await self.cl_set(self.cfg.feedback.bypass, True)
                cfl = -1
                cmode = -1
                cpwr = -1

                while self.c_bypass:
                    if self.c_flow != cfl:
                        print("* FLOW", self.c_flow)
                        cfl = self.c_flow
                    await self.set_flow_pwm(self.c_flow)

                    if self.c_bypass_mode != cmode:
                        print("* MODE", self.c_bypass_mode)
                        cmode = self.c_bypass_mode
                        await self.cl_set(self.cfg.cmd.mode.path, value=self.c_bypass_mode)

                    if self.c_bypass_power != cpwr:
                        print("* POWER", self.c_bypass_power)
                        cpwr = self.c_bypass_power
                        await self.cl_set(self.cfg.cmd.power, value=self.c_bypass_power)

                    await self.wait()
                await self.cl_set(self.cfg.feedback.bypass, False)
                print("*** BYPASS OFF ***")
                run = Run.down

            # fmt: off
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
            elif orun == Run.off and run == Run.down:
                run = Run.off
            elif orun == Run.down and run == Run.off:
                pass
            elif orun == Run.ice and run in (Run.wait_flow,Run.wait_time):
                pass
            else:
                raise ValueError(f"Cannot go from {orun.name} to {run.name}")
            # fmt: on

            # Handle state changes

            # redirect for shutdown
            if run == Run.off:
                if orun is None and (self.state.t_pellet_on and not self.cm_pellet):
                    pass
                elif orun not in (
                    Run.off,
                    Run.wait_time,
                    Run.wait_flow,
                    Run.wait_power,
                    Run.down,
                ):
                    run = Run.down

            # Report
            if orun != run:
                print(f"*** STATE: {run.name}")

            # Leaving a state
            if orun is None:  # startup
                # Restarting: restart the timer if required
                if self.state.t_change is not None:
                    self.state.t_change = self.time

                # assume PIDs are restored from state
                # assume PWM is stable
                if run == Run.run:
                    last = self.state.get("load_last", None)
                    if last is not None:
                        await self.set_load(last)

            oheat_off, heat_off = heat_off, None
            self.wp_on = run == Run.run

            # Entering a state
            if orun == run:  # no change
                heat_off = oheat_off

                task_status.started()
                task_status = anyio.TASK_STATUS_IGNORED
                await self.wait()

            elif run == Run.off:  # nothing happens
                heat_off = False
                self.state.t_change = None
                t_change_max = None
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
                self.state.t_change = self.time
                if t_change_max is None or t_change_max < self.cfg.lim.times.start:
                    t_change_max = self.cfg.lim.times.start

                await self.cl_set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off)
                await self.pid.flow.setpoint(self.cfg.misc.start.flow.init.rate)
                self.pid.flow.move_to(
                    self.cfg.misc.start.flow.init.rate,
                    self.cfg.misc.start.flow.init.pwm,
                )
                await self.set_flow_pwm(self.cfg.misc.start.flow.init.pwm)

            elif run == Run.flow:  # wait for decent throughput
                if t_change_max is None or t_change_max < self.cfg.lim.times.start:
                    t_change_max = self.cfg.lim.times.start

            elif run == Run.wait_power:  # wait for pump to draw power
                if t_change_max is None or t_change_max < self.cfg.lim.times.start:
                    t_change_max = self.cfg.lim.times.start
                await self.pid.flow.setpoint(self.cfg.misc.start.flow.power.rate)
                self.pid.flow.move_to(
                    self.cfg.misc.start.flow.power.rate,
                    self.cfg.misc.start.flow.power.pwm,
                )
                # self.pid.flow.move_to(self.r_flow, self.state.last_pwm)
                await self.set_load(self.cfg.misc.start.power)

            elif run == Run.temp:  # wait for outflow-inflow>2
                if t_change_max is None or t_change_max < self.cfg.lim.times.start:
                    t_change_max = self.cfg.lim.times.start
                await self.pid.flow.setpoint(self.cfg.misc.start.flow.power.rate)
                await self.set_flow_pwm(self.cfg.misc.start.flow.power.pwm)

            elif run == Run.run:  # operation
                heat_off = False
                self.state.t_change = None
                t_change_max = None
                self.state.setdefault("t_run", self.time)
                if orun is not None:
                    self.state.scaled_low = 1.0
                    await self.log_zero()
                    self.pid.limit.reset()
                    self.pid.load.reset()
                    self.pid.buffer.reset()
                else:
                    self.state.setdefault("scaled_low", 1.0)
                    await self.pid.flow.log_value(0)
                self.pid.pump.move_to(self.t_out, self.state.last_pwm)
                self.state.load_last = None

            elif run == Run.ice:  # wait for ice condition to stop
                await self.log_zero()

                if self.state.t_change is None:
                    self.state.t_change = self.time
                if t_change_max is None or t_change_max < self.cfg.lim.times.ice:
                    t_change_max = self.cfg.lim.times.ice
                heat_off = True
                await self.pid.flow.setpoint(self.cfg.misc.de_ice.flow)
                self.pid.flow.move_to(self.cfg.misc.de_ice.flow, self.cfg.misc.de_ice.pwm)

                await self.cl_set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off)
                await self.cl_set(self.cfg.cmd.power, value=0)

            elif run == Run.down:  # wait for outflow-inflow<2 for n seconds, cool down
                await self.log_zero()
                if self.state.t_change is None:
                    self.state.t_change = self.time
                if t_change_max is None or t_change_max < self.cfg.lim.times.stop:
                    t_change_max = self.cfg.lim.times.stop

                heat_off = True
                await self.pid.flow.setpoint(
                    self.cfg.misc.stop.flow if orun != Run.off else self.lim.defrost.flow,
                )
                await self.cl_set(self.cfg.cmd.mode.path, value=self.cfg.cmd.mode.off)
                await self.cl_set(self.cfg.cmd.power, value=0)

            else:
                raise ValueError(f"State ?? {run!r}")

            if self.state.t_change is not None and self.time - self.state.t_change > t_change_max:
                raise TimeoutError("Time exceeded. Turning off.")

            orun = run
            self.state.run = int(run)
            await self.cl.set(self.cfg.sensor.pump.state, self.state.run, idem=True)

            # When de-icing starts, shut down (for now).
            if self.m_ice:
                if not m_ice:
                    print("*** ICE ***")
                    m_ice = True
                    await self.cl_set(self.cfg.feedback.ice, True)
                    run = Run.ice
                    continue
            else:
                if m_ice:
                    await self.cl_set(self.cfg.feedback.ice, False)
                    print("*** NO ICE ***")
                m_ice = False

            # Process the main switch

            if self.m_ice:
                pass
            elif not self.cm_wp or bool(self.m_errors):
                if cm_wp is not False:
                    cm_wp = False
                    await self.cl_set(self.cfg.feedback.wp, self.cm_wp)

                    if run != Run.off:
                        print("OFF 7    ")
                    run = Run.off
                    continue
            else:
                if cm_wp is not True:
                    cm_wp = True
                    await self.cl_set(self.cfg.feedback.wp, self.cm_wp)

            # Process the heating control switch

            if self.cm_heat != cm_heat:
                await self.cl_set(self.cfg.feedback.heat, self.cm_heat)
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

            self.state.avg_heat += (
                self.t_heat - self.state.avg_heat
            ) * self.cfg.lim.pellet.start.heat.scale
            if self.state.avg_heat_t == 0:
                self.state.avg_heat_t = self.heat_dest
            else:
                self.state.avg_heat_t += (
                    self.heat_dest - self.state.avg_heat_t
                ) * self.cfg.lim.pellet.start.heat.scale
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
                t_set_on = max(tw_nom, th_nom)  # test: buffer top
                t_set_off = max(tw_nom, th_low)  # test: buffer mid

                t_cur = self.tb_heat
            else:
                t_nom = tw_nom
                t_low = tw_low
                t_adj = tw_adj
                t_set_on = tw_nom  # test: buffer top
                t_set_off = tw_nom  # test: buffer mid

                t_cur = self.tb_water

            # PID controller settings
            f = val2pos(t_nom, t_cur, t_adj, clamp=True)
            max2 = (self.cfg.adj.max_max + self.cfg.adj.max) / 2
            t_limit = min(
                max2,
                max(self.tb_low + self.cfg.misc.heat.delta, t_adj + self.cfg.adj.more),
            )
            tp_limit = min(
                self.cfg.adj.max_pellet,
                t_adj + self.cfg.adj.more,
                # t_cur + self.cfg.adj.more,
            )
            if t_cur < t_low:
                adj = (t_low - t_cur) * self.cfg.adj.low.factor
                t_limit = min(t_limit + adj, max2)
                tp_limit += adj
            t_pump = min(self.cfg.adj.max, pos2val(t_low, f, t_limit + 0.2 * (t_low - t_limit)))
            # t_load = t_adj + self.cfg.adj.buffer
            t_buffer = t_low + self.cfg.adj.low.buffer  # <0

            self.t_adj = t_adj
            self.t_nom = t_nom
            self.t_low = t_low
            self.t_limit = t_limit

            tplim = tp_limit
            # increase temp settings when starting up

            if self.pellet_on is False:
                try:
                    tplim = min(
                        self.cfg.adj.max_pellet,
                        self.cfg.adj.pellet.startup.buf + max(self.tb_water, self.tb_heat),
                    )
                    for p in self.cfg.adj.pellet.startup.patch.path:
                        await self.cl_set(p, tplim, idem=True)
                    await self.cl_set(self.cfg.cmd.pellet.load, 1, idem=True)
                except AttributeError:
                    pass

            await self.cl_set(
                self.cfg.cmd.pellet.temp,
                max(self.cfg.lim.pellet.temp.min, tplim),
                idem=True,
            )

            # on/off thresholds
            # t_set_on = (t_low + t_adj) / 2  # top

            # t_load is later
            await self.pid.buffer.setpoint(t_buffer)
            await self.pid.limit.setpoint(t_limit)
            await self.pid.pump.setpoint(t_pump)

            # State handling

            if run == Run.off:  # nothing happens
                r = "????"
                if not cm_wp:
                    r = "main"
                elif bool(self.m_errors):
                    r = "errn"
                elif self.force_on:
                    print("** PS5     ")
                    r = None
                    self.force_on = False
                elif self.state.t_pellet_on is True:
                    if self.pellet_load < 0.9:
                        r = "psml"
                    elif self.tb_low > self.cfg.lim.start:
                        r = "phlo"
                    elif self.tb_water < tw_nom:
                        print("** PS1", tw_nom, self.tb_water, "        ")
                        r = None
                    elif self.tb_heat < th_nom - self.cfg.lim.pellet.start.buffer:
                        r = None
                        print(
                            "** PS3",
                            th_nom,
                            self.tb_heat,
                            self.cfg.lim.pellet.start.buffer,
                            "      ",
                        )
                    elif self.state.avg_heat_t > th_nom - self.cfg.lim.pellet.start.heat.delta:
                        r = "phok"
                    else:
                        r = "ptmp"
                    if r is None:
                        self.state.start_p = True
                elif t_cur < t_set_on:
                    print("** PS4", t_cur, t_set_on, "      ")
                    r = None
                    self.state.start_p = False
                else:
                    r = "temp"
                if r is None:
                    run = Run.wait_time
                    self.r_no = None
                    continue
                elif min(self.t_out, self.t_in) < self.cfg.lim.defrost.temp:
                    run = Run.down
                    continue
                if r != "pell":
                    print(
                        f"      -{r} cur={t_cur:.1f} on={t_set_on:.1f}       ",
                        end="\r",
                    )
                sys.stdout.flush()
                self.r_no = r

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
                l_flow = await self.pid.flow(self.r_flow)
                print(f"Flow: {self.r_flow:.1f} : {l_flow:.3f}       ")
                await self.set_flow_pwm(l_flow)

            elif run == Run.wait_power:  # wait for pump to draw power
                if self.m_power >= self.cfg.misc.min_power:
                    run = Run.temp
                    continue
                l_flow = await self.pid.flow(self.r_flow)
                print(f"Flow: {self.r_flow:.1f} : {l_flow:.3f} p={self.m_power:.1f}       ")
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
                await self.handle_flow(True)
                if not self.m_ice:
                    if self.tb_mid > t_set_off:
                        print("OFF 4A", t_cur, t_adj, self.tb_mid, t_set_off, "    ")
                        run = Run.off
                    elif self.tb_low >= t_low:
                        print("OFF 5A", t_cur, t_adj, self.tb_low, t_low, "    ")
                        run = Run.off
                    else:
                        run = Run.wait_time  ## XXX instead: off = wait_time? # wait_flow
                    continue

            elif run == Run.down:  # wait for outflow-inflow<2 for n seconds, cool down
                if (
                    min(self.t_out, self.t_in) > self.cfg.lim.defrost.temp
                    and max(self.t_out, self.t_in) < self.cfg.lim.idle
                ):
                    run = Run.off
                    continue
                await self.handle_flow()
                if (
                    min(self.t_out, self.t_in) > self.cfg.lim.defrost.temp
                    and self.t_out - self.t_in < self.cfg.misc.stop.delta
                ):
                    # print("OFF 1",self.t_out, self.t_in, "    ")
                    run = Run.off
                    continue

            else:
                raise ValueError(f"State ?? {run!r}")

            heat_ok = False
            if self.state.t_pellet_on:
                heat_ok = True
            elif run == Run.temp and self.tb_low + self.cfg.misc.heat.delta > t_adj:
                if cm_heat:
                    # if the temperature delta is too low so that the heat pump
                    # won't do much at startup, run the heating system to get more
                    # cold water to its inflow
                    heat_ok = True
                    self.log_hc(10)
                    self.state.heat_ok = 1  # start now
                else:
                    # ugh
                    self.log_hc(11)
                    t_adj = self.tb_low + self.cfg.misc.heat.delta

            elif run not in {Run.off, Run.wait_time, Run.run, Run.down}:
                self.log_hc(7)
            elif heat_off:
                self.log_hc(8)
            elif (
                self.tb_heat
                if self.m_switch  # or self.state.t_pellet_on
                else pos2val(
                    self.tb_heat,  # buffer heat
                    (self.state.last_pwm or 0) / self.cfg.adj.low.pwm,
                    self.t_out,  # flow put
                    clamp=True,
                )
            ) < self.c_heat + self.cfg.adj.low.pre_heat:
                if run != Run.run or self.m_switch:
                    self.log_hc(
                        9,
                        self.m_switch or self.state.t_pellet_on,
                        self.tb_heat,
                        self.c_heat,
                    )

            else:
                heat_ok = True

            if not heat_ok or not cm_heat:
                # If the incoming water is too cold, turn off heating
                # We DO NOT turn heating off while running: danger of
                # overloading the heat pump due to temperature jump,
                # because the backflow is now fed by warm buffer from the
                # buffer instead of cold water returning from radiators,
                # esp. when they have been cooling off for some time
                #
                # This doesn't apply when the heat pump is routed to the
                # water buffer (m_switch is set) because in this case the
                # buffer is cold anyway.

                if cm_heat and self.state.heat_ok is False:
                    pass
                elif cm_heat and run == Run.run and not self.m_switch:
                    self.log_hc(2)
                else:
                    # turn off heating
                    self.log_hc(1)
                    if "pump" in self.cfg.feedback:
                        await self.cl_set(self.cfg.feedback.pump, False, idem=True)
                    if heat_pin is not None:
                        GPIO.output(heat_pin, False)
                    elif "path" in self.cfg.setting.heat.mode:
                        await self.cl_set(
                            self.cfg.setting.heat.mode.path,
                            self.cfg.setting.heat.mode.off,
                        )
                    self.state.heat_ok = False
            elif self.state.heat_ok is True:
                self.log_hc(3)
            elif self.state.heat_ok is False:
                self.log_hc(4)
                self.state.heat_ok = self.time
            elif self.time - self.state.heat_ok > self.cfg.setting.heat.mode.delay:
                # turn on heating
                self.log_hc(5)
                if "pump" in self.cfg.feedback:
                    await self.cl_set(self.cfg.feedback.pump, True, idem=True)
                if heat_pin is not None:
                    GPIO.output(heat_pin, True)
                # no "elif" here, this is intentional
                if "path" in self.cfg.setting.heat.mode:
                    await self.cl_set(
                        self.cfg.setting.heat.mode.path,
                        self.cfg.setting.heat.mode.on,
                    )
                self.state.heat_ok = True

            else:
                # wait
                self.log_hc(6)

            if run != Run.run:
                continue
                # END not running

            # RUNNING ONLY after this point

            if self.pellet_on and self.tb_heat > t_cur:
                # if the pellet boiler is (a) on, (b) hot enough

                #               if not self.state.start_p and self.m_pellet >= t_low:
                #                   # turn off when the pellet burner is warm as it's turned on
                #                   print("OFF 2",self.m_pellet,t_low,self.state.start_p, "    ")
                #                   run = Run.off
                #                   continue

                # the next two conditions cut off early.
                if t_cur >= t_nom + self.cfg.lim.pellet.stop.buffer:
                    print("OFF 6", t_cur, t_nom, "    ")
                    run = Run.off
                    continue

                if t_cur >= t_adj:
                    print("OFF 3", t_cur, t_low, "    ")
                    run = Run.off
                    continue

            if self.m_power < self.cfg.misc.min_power:
                # might be ice or whatever, so wait
                if t_no_power is None:
                    t_no_power = self.time
                elif self.time - t_no_power > 30:
                    print(
                        f"\nNO POWER USE {self.m_power} {self.cfg.misc.min_power}",
                        "    ",
                    )
                    run = Run.off
                    continue
            else:
                t_no_power = None

            if self.state.t_pellet_on:
                t_load = min(t_adj + self.cfg.adj.pellet.load, self.cfg.adj.pellet.max)
            else:
                t_load = min(t_adj + self.cfg.adj.buffer, self.cfg.adj.max)
            await self.pid.load.setpoint(t_load)

            # The pump rate is controlled by its intended output heat now
            if self.t_out > self.cfg.adj.max_max:
                l_pump = 1
                i_pump = ()
                self.pid.pump.move_to(self.t_out, 1.0)
                # emergency handler
            else:
                l_pump, i_pump = await self.pid.pump(self.t_out, split=True)
                # self.pid.flow.move_to(self.r_flow, l_pump)
            self.state.last_pwm = l_pump

            l_load, i_load = await self.pid.load(t_cur, split=True)
            l_buffer, i_buffer = await self.pid.buffer(self.tb_low, split=True)
            l_limit, i_limit = await self.pid.limit(self.t_out, split=True)

            if True:
                w = val2pos(t_adj - self.cfg.adj.more, t_cur, t_adj)
            else:
                # if no heating OR the heating req is lower than the water's,
                # don't try steady-state mode.
                # TODO refine steady-state instead
                w = -1
            l_buf = pos2val(l_limit, w, l_buffer, clamp=True)
            lim = min(l_buf, l_limit, l_load)
            self.state.scaled_low += (lim - self.state.scaled_low) * (
                self.cfg.lim.low.pellet.scale if self.state.t_pellet_on else self.cfg.lim.low.scale
            )

            tt = self.time
            if tt - tlast > 5 or self.t_out > self.cfg.adj.max:
                tlast = tt
                pr = (
                    f"t={int(tt) % 1000:03d}",
                    f"buf={t_cur:.1f}/{self.tb_mid:.1f}/{self.tb_low:.1f}",
                    f"t={self.t_out:.1f}/{self.t_in:.1f}",
                    f"P={l_pump:.3f}",
                    # *(f"{x :6.3f}" for x in i_pump),
                    f"lim{'=' if lim == l_limit else '_'}{l_limit:.3f}",
                    f"load{'=' if lim == l_load else '_'}{l_load:.3f}",
                    f"buf{'=' if lim == l_buf else '_'}{l_buf:.3f}",
                    # *(f"{x :6.3f}" for x in i_pump),
                    # *(f"{x :6.3f}" for x in i_buffer),
                    # *(f"{x :6.3f}" for x in i_load),
                    f"w={w:.2f} lb={l_buffer:.2f}",
                )
                print(*pr)

                # suppress set-but-not-used warnings
                i_load, i_buffer, i_limit, i_pump  # noqa:B018

            # l_buffer is disregarded when the buffer head is too far
            # below its setpoint. Otherwise the initial surge would delay heat-up
            print(
                f" H={self.hc_pos}",
                f"W={w:.1f}",
                # f"res={l_buf :.2f}",
                f"lim={lim:.2f}",
                f"cur={t_cur:.1f}",
                f"hlow={th_low:.1f}",
                f"hadj={th_adj:.1f}",
                f"wlow={tw_low:.1f}",
                f"buf={t_buffer:.1f}",
                # f"off={t_set_off :.1f}",
                f"scl={self.state.scaled_low:.3f}",
                f"tbh={self.tb_heat:.1f}",
                f"ch={self.c_heat:.1f}",
                end="\r",
            )
            sys.stdout.flush()

            await self.set_load(lim)
            await self.set_flow_pwm(l_pump)
            self.state.load_last = lim

            # COP
            if self.m_power:
                cop = 1.16 * 60 * self.r_flow * (self.t_out - self.t_in) / 1000 / self.m_power
                self.m_cop += 0.0001 * self.m_power * (cop - self.m_cop)
                if n_cop <= 0:
                    n_cop = 100
                    await self.cl_set(self.cfg.sensor.cop, self.m_cop)
                else:
                    n_cop -= 1

            # Finally, we might want to turn the heat exchanger off
            # if the buffer head temperature is high enough.
            if self.state.t_pellet_on and self.state.scaled_low < self.cfg.lim.low.pellet.limit:
                print("OFF SCALE PELLET    ")
                run = Run.off
                continue
            if t_cur >= t_adj:
                # Running long enough, or lower buffer temperature higher than goal?
                if self.state.scaled_low < (
                    self.cfg.lim.low.pellet.limit
                    if self.state.t_pellet_on
                    else self.cfg.lim.low.limit
                ):
                    print("OFF SCALED    ")
                    run = Run.off
                    continue
                if (
                    self.time - self.state.t_run > self.cfg.lim.power.time
                    and self.tb_mid > t_set_off
                ):
                    print("OFF 4", t_cur, t_adj, self.tb_mid, t_set_off, "    ")
                    run = Run.off
                    continue
                elif self.tb_low >= t_low:
                    print("OFF 5", t_cur, t_adj, self.tb_low, t_low, "    ")
                    run = Run.off
                    continue

    async def run_set_pellet(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """run the pellet burner when it's too cold for the heat pump"""
        task_status.started()

        if self.state.get("t_pellet_on", None) is None:
            self.state.t_pellet_on = (await self.cl.get(self.cfg.cmd.pellet.wanted)).value

        t_on = self.state.t_pellet_on
        if not isinstance(t_on, bool):
            await self.cl_set(self.cfg.cmd.pellet.load, 1.0)
            while self.tb_heat is None:
                await self.wait()

        tlast = 0
        o_r = ""
        while True:
            await self.wait()
            if self.t_adj is None:
                # starting up
                continue

            if (
                self.m_pellet_state in (0, 1, 3, 5, 6, 7, 8, 9)
                or 21 <= self.m_pellet_state <= 35
                or self.m_pellet_state >= 43
            ):
                self.state.t_pellet_on = False
                self.pellet_on = False
                self.pid.load.Kd = self.cfg.pid.load.d
                self.pid.load.Tf = self.cfg.pid.load.tf
            elif self.m_pellet_state not in (2, 4):
                self.pellet_on = False
                self.state.t_pellet_on = self.time
            else:
                if self.m_pellet_state == 4:
                    if not self.pellet_on:
                        self.pellet_on = True
                        try:
                            for p in self.cfg.adj.pellet.startup.patch.path:
                                await self.cl_set(
                                    p,
                                    self.cfg.adj.pellet.startup.patch.stop,
                                    idem=True,
                                )
                        except AttributeError:
                            pass

                    if self.time - self.state.t_pellet_on > self.cfg.lim.pellet.t_min:
                        self.state.t_pellet_on = True

                self.pid.load.Kd = self.cfg.adj.pellet.pid.load.d
                self.pid.load.Tf = self.cfg.adj.pellet.pid.load.tf

                t_load = min(self.t_adj + self.cfg.adj.pellet.load, self.cfg.adj.pellet.max)
                t_buffer = self.t_low + self.cfg.adj.low.buffer  # <0
                t_cur = self.tb_heat

                await self.pid.p_load.setpoint(t_load)
                await self.pid.p_buffer.setpoint(t_buffer)

                l_buffer = await self.pid.p_buffer(self.tb_low)
                w = val2pos(self.t_adj - self.cfg.adj.more, self.tb_heat, self.t_adj)
                l_buf = l_buffer

                l_load, i_load = await self.pid.p_load(t_cur, split=True)
                if self.cm_pellet_force is not None:
                    # external forcing input
                    lim = self.cm_pellet_force
                    self.pid.p_load.move_to(self.tb_heat, lim)
                    r = "F"
                elif t_cur + self.cfg.adj.pellet.low < self.state.pp_load.setpoint:
                    r = "B"
                    # pre-load the controller with a biased D
                    # so that it doesn't immediately go below 1
                    # when the temperature rises further
                    lim = 1.0
                    self.pid.p_load.move_to(
                        self.tb_heat + (t_load - self.tb_heat) * self.cfg.adj.pellet.preload.low,
                        1.0,
                    )
                elif self.wp_on:
                    r = "C"
                    await self.cl_set(self.cfg.cmd.pellet.load, 1.0, idem=True)
                    self.pid.p_load.move_to(
                        self.tb_heat + (t_load - self.tb_heat) * self.cfg.adj.pellet.preload.wp,
                        1.0,
                    )
                    lim = 1.0
                else:
                    r = "-"
                    l_buf = pos2val(l_load, w, l_buffer, clamp=True)
                    lim = min(l_buf, l_load)

                tt = self.time
                if o_r == r and not self.wp_on and tt - tlast > 5 and self.r_no is not None:
                    tlast = tt
                    pr = (
                        f"t={int(tt) % 1000:03d}",
                        f"r={r}",
                        f"buf={t_cur:.1f}/{self.tb_mid:.1f}/{self.tb_low:.1f}",
                        # f"t={self.t_out :.1f}/{self.t_in :.1f}",
                        # f"Pump={l_pump :.3f}",
                        # *(f"{x :6.3f}" for x in i_pump),
                        f"load{'=' if lim == l_load else '_'}{l_load:.3f}",
                        f"buf{'=' if lim == l_buffer else '_'}{l_buffer:.3f}",
                        f"avg_h={self.state.avg_heat:.1f}",
                        f"{self.state.avg_heat - self.state.avg_heat_t:.1f} ",
                    )
                    pr += tuple(f"{x:6.3f}" for x in i_load)
                    print(*pr, "    ")
                o_r = r

                if self.m_pellet_state in (
                    31,
                    32,
                ):
                    xlim = 1
                else:
                    xlim = lim

                await self.cl_set(self.cfg.cmd.pellet.load, xlim, idem=True)
                self.pellet_load = lim

                tw_nom = self.c_water
                tw_low = tw_nom + self.cfg.adj.low.water
                tw_adj = tw_nom + self.cfg.adj.water  # noqa:F841

                th_nom = self.c_heat
                th_low = th_nom + self.cfg.adj.low.heat
                th_adj = th_nom + self.cfg.adj.heat  # noqa:F841

                if not self.wp_on or self.r_no is not None:
                    print(
                        f" H={self.hc_pos}",
                        f"W={w:.1f}",
                        # f"res={l_buf :.2f}",
                        f"lim={lim:.2f}",
                        f"cur={t_cur:.1f}",
                        f"hlow={th_low:.1f}",
                        f"wlow={tw_low:.1f}",
                        f"buf={t_buffer:.1f}",
                        f"tbh={self.tb_heat:.1f}",
                        f"ch={self.c_heat:.1f}",
                        f"{self.r_no}",
                        end="\r",
                    )
                    sys.stdout.flush()

    async def run_temp_thresh(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "temperature thresholds for pellet burner on/off switch"
        task_status.started()
        run = (await self.cl.get(self.cfg.cmd.pellet.wanted)).value

        while True:
            for _ in range(10):
                await self.wait()

            if (
                not run
                and self.m_pellet_state in (0, 30, 31, 32)
                and (
                    not self.cm_wp
                    or (
                        self.m_air < self.cfg.misc.pellet.current
                        and min(self.m_air, self.m_air_pred) < self.cfg.misc.pellet.predict - 0.15
                    )
                )
            ):
                print("  PELLET ON  ")
                run = True

                self.pid.p_load.move_to(self.tb_heat, 1.0)
                self.pid.p_buffer.move_to(self.tb_low, 1.0)

            elif run and (
                self.m_air > self.cfg.misc.pellet.current
                and min(self.m_air, self.m_air_pred) > self.cfg.misc.pellet.predict + 0.15
                and self.t_low is not None
                and self.tb_heat > self.t_low
                and self.t_ext_avg is not None
                and self.t_ext_avg > self.cfg.misc.pellet.avg_off
                and isinstance(self.state.t_pellet_on, bool)
                and self.cm_wp
            ):
                run = False
                self.state.t_pellet_on = False
                self.pellet_load = 0
                print("  PELLET OFF  ")

            else:
                continue

            await self.cl_set(self.cfg.cmd.pellet.wanted, run)
            if "pellet" in self.cfg.feedback:
                await self.cl_set(self.cfg.feedback.pellet, run)

    async def run_set_heat(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """set the goal for heating"""
        cf = self.cfg.adj.curve

        locks = attrdict(day=False, night=False)
        dest = cf.dest
        t_cur = None
        _lock = anyio.Lock()

        async def _upd():
            nonlocal cf, dest, locks, t_cur, _lock
            if t_cur is None:
                print("t_cur bad")
                return 10
            async with _lock:
                if self.heat_dest is None:
                    print("t_cur OK")
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

                ht = vt(t_cur, dest, cf)
                logger.debug("HZ: %.1f %.1f", ht, t_cur)
                await self.cl_set(cf.setting, int(ht + 0.8), idem=True)
                self.heat_dest = ht

                return delay

        async def sf_day_night(sf, dn, nd, *, task_status):
            async with self._cl.watch(sf[dn].cmd, max_depth=0, fetch=True) as msgs:
                task_status.started()
                async for m in msgs:
                    try:
                        val = m.value
                    except AttributeError:
                        continue
                    await self.cl_set(sf[dn].state, val)
                    if val:
                        await self.cl_set(sf[nd].cmd, False, idem=True)
                        await self.cl_set(sf[nd].state, False, idem=True)
                        locks[nd] = False
                    locks[dn] = val
                    await _upd()

        async def update_dest(*, task_status):
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
            async for m in msgs:
                if "value" not in m:
                    if m.get("state", "") == "uptodate":
                        await tg.start(update_dest)
                        await tg.start(sf_day_night, sf, "day", "night")
                        await tg.start(sf_day_night, sf, "night", "day")
                        task_status.started()
                    else:
                        continue
                elif t_cur is None:
                    t_cur = m.value
                    continue
                else:
                    self.t_ext_avg = t_cur = m.value
                await _upd()

    async def handle_flow(self, use_min=False):
        """
        Flow handler while not operational
        """
        l_flow = await self.pid.flow(self.r_flow)
        l_temp = await self.pid.pump(self.t_out)
        print(
            f"t={self.time % 1000:03.0f}",
            f"Pump:{l_flow:.3f}/{l_temp:.3f}",
            f"flow={self.r_flow:.1f}",
            f"t={self.t_out:.1f}",
            "      ",
        )
        res = max(l_flow, l_temp)
        if use_min:
            res = max(res, self.cfg.misc.de_ice.min)
        # self.pid.flow.move_to(self.r_flow, res)
        # self.pid.pump.move_to(self.t_out, res)
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
            print("Waiting", " ".join(self._want))
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
        try:
            with anyio.fail_after(self.cfg.lim.times.stop):
                while self.t_out - self.t_in > self.cfg.misc.stop.delta:
                    await self.handle_flow()
                    await self.wait()
        finally:
            await self.set_flow_pwm(0)
            self.state.run = 0
        await self.save()

    async def run_init(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "setup listeners"
        cfg = self._cfg
        async with anyio.create_task_group() as tg:
            await tg.start(self._kv, cfg.cmd.flow, "c_flow")
            await tg.start(self._kv, cfg.cmd.bypass.cmd, "c_bypass")
            await tg.start(self._kv, cfg.cmd.bypass.mode, "c_bypass_mode")
            await tg.start(self._kv, cfg.cmd.bypass.power, "c_bypass_power")
            await tg.start(self._kv, cfg.cmd.wp, "cm_wp")
            await tg.start(self._kv, cfg.cmd.heat, "cm_heat")
            await tg.start(self._kv, cfg.cmd.pellet.run, "cm_pellet")
            await tg.start(self._kv, cfg.cmd.pellet.force, "cm_pellet_force")
            await tg.start(self._kv, cfg.setting.heat.day, "c_heat")
            await tg.start(self._kv, cfg.setting.heat.night, "c_heat_night")
            await tg.start(self._kv, cfg.setting.water, "c_water")
            # await tg.start(self._kv, cfg.setting.passthru, "m_passthru")
            await tg.start(self._kv, cfg.sensor.pump["in"], "t_in")
            await tg.start(self._kv, cfg.sensor.pump["out"], "t_out")
            await tg.start(self._kv, cfg.sensor.temp.heat, "t_heat")
            await tg.start(self._kv, cfg.sensor.pump.flow, "r_flow")
            await tg.start(self._kv, cfg.sensor.pump.ice, "m_ice")
            await tg.start(self._kv, cfg.sensor.cop, "m_cop")
            await tg.start(self._kv, cfg.sensor.pellet.state, "m_pellet_state")
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

    #           yprint(
    #               {
    #                   k: v
    #                   for k, v in vars(self).items()
    #                   if not k.startswith("_") and isinstance(v, (int, float, str))
    #               },
    #           )

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
        await fkv("c_bypass")
        await fkv("cm_wp")
        await fkv("cm_heat")
        await fkv("cm_pellet")
        await fkv("cm_pellet_force")
        await fkv("c_heat")
        await fkv("c_heat_night")
        await fkv("c_water")
        # await fkv("m_passthru")
        await fkv("t_in")
        await fkv("t_out")
        await fkv("t_heat")
        await fkv("r_flow")
        await fkv("m_ice")
        await fkv("m_cop")
        await fkv("m_pellet_state")
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
        if isinstance(self.cfg.state, Path):
            await self.cl.set(self.cfg.state, value=self.state)
        else:
            f = anyio.Path(self.cfg.state)
            fn = anyio.Path(self.cfg.state + ".n")
            fs = io.StringIO()
            yprint(self.state, fs)
            await fn.write_text(fs.getvalue())
            await fn.rename(f)

    async def run_solvis_mon(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        again = anyio.Event()
        kick = anyio.Event()
        cfg = self.cfg.misc.mon_solvis

        task_status.started()  # well not really but the caller doesn't care

        async def s_run():
            nonlocal again, kick
            while True:
                async with await anyio.open_process(
                    ["moat", "modbus", "dev", "poll", cfg.data],
                    stdin=subprocess.DEVNULL,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                ) as p:
                    try:
                        kick.set()
                        kick = anyio.Event()
                        await again.wait()
                    finally:
                        p.kill()
                    await anyio.sleep(3)

        async with anyio.create_task_group() as tg:
            tg.start_soon(s_run)
            await kick.wait()
            await anyio.sleep(60)

            async with self.cl.watch(cfg.err, long_path=False, fetch=True, max_depth=0) as msgs:
                async for m in msgs:
                    if "value" not in m:
                        continue
                    if not m.value:
                        continue
                    m = await self.cl.get(cfg.err / 1 / "code")
                    if m.value == 26:
                        print("\nRESTART SOLVIS")
                        again.set()
                        again = anyio.Event()
                        try:
                            with anyio.fail_after(15):
                                await kick.wait()
                        except TimeoutError:
                            print("\nRESTART SOLVIS ERROR")
                        else:
                            print("\nRESTART SOLVIS OK")

                    else:
                        print("\nERROR SOLVIS", m.value, file=sys.stderr)


class fake_cl:
    "fake MoaT-KW client, for playbacks"

    def __init__(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    async def set(self, path, value, **_k):
        "don't set anything, we're replaying"
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
@click.option("-c", "--config", type=click.Path("r"), help="config file")
async def cli(ctx, config):
    """
    Manage a Solvis heat pump controller

    Given a SolvisLea heat pump (and another, modbus-controllable,
    source of heat), teach it to behave.
    """
    ctx.obj = attrdict()
    cfg = yload(CFG, attr=True)
    if config is not None:
        with open(config, "r") as cff:
            cfg = combine_dict(yload(cff, attr=True), cfg, cls=attrdict)
    ctx.obj.cfg = cfg
    ctx.obj.cfgf = config

    global GPIO
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        pass
    else:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)


@cli.command
@click.pass_obj
async def solvis_mon(obj):
    async with open_client(**mcfg.kv) as cl:
        d = Data(obj.cfg, cl, no_op=True)
        await d.run_solvis_mon()


@cli.command
@click.pass_obj
@click.option("-r", "--record", type=click.File("w"))
@click.option("-n", "--no-save", is_flag=True)
@click.option("-f", "--force-on", is_flag=True)
async def run(obj, record, force_on, no_save):
    "Heat pump controller. Designed to run continuously"
    async with open_client(**mcfg.kv) as cl:
        d = None
        try:
            async with anyio.create_task_group() as tg:
                try:
                    if isinstance(obj.cfg.state, Path):
                        state = await cl.get(obj.cfg.state)
                        try:
                            state = state.value
                        except AttributeError:
                            state = None
                    else:
                        with open(obj.cfg.state) as sf:
                            state = yload(sf, attr=True)
                except OSError:
                    state = None
                d = Data(obj.cfg, cl, record=record, no_op=no_save, state=state)
                d.force_on = force_on

                if obj.cfgf:
                    await tg.start(d.reload_cfg, obj.cfgf)
                await tg.start(d.run_init)
                await tg.start(d.err_mon)
                await tg.start(d.run_temp_thresh)
                await tg.start(d.run_set_heat)
                await tg.start(d.run_set_pellet)
                if not no_save:
                    try:
                        obj.cfg.misc.mon_solvis.err
                    except AttributeError:
                        pass
                    else:
                        await tg.start(d.run_solvis_mon)

                    await tg.start(d.saver)
                await tg.start(d.run_pump)
                print("ALL READY")
        finally:
            if d is not None:
                with anyio.fail_after(30, shield=True):
                    async with anyio.create_task_group() as tg:
                        await tg.start(d.run_init)
                        await d.off()
                        tg.cancel_scope.cancel()


@cli.command
@click.pass_obj
@click.argument("record", type=click.File("r"))
async def replay(obj, record):
    "Replay a previous run, for testing"
    async with fake_cl() as cl, anyio.create_task_group() as tg:
        d = Data(obj.cfg, cl)
        await tg.start(d.run_rec, record, tg)
        await tg.start(d.run_fake)
        await tg.start(d.run_pump)


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


class t_iter:
    def __init__(self, interval):
        self.interval = interval

    def time(self):
        return time.monotonic()

    async def sleep(self, dt):
        await anyio.sleep(max(dt, 0))

    def __aiter__(self):
        self._t = self.time() - self.interval
        return self

    def __anext__(self):
        t = self.time()
        dt = self._t - t
        if dt > 0:
            self._t += self.interval
        else:
            self._t = t + self.interval
            dt = 0
        return self.sleep(dt)


# output:
#    flow:
#        pin: 4
#        freq: 200
#        path: !P heat.s.pump.pid
#        override:
#            flag: !P home.ass.state.input_boolean.test_override_on.state
#            val: !P home.ass.state.input_number.test_override_pct.state

#           GPIO.output(heat_pin, False)
#           GPIO.setup(heat_pin, GPIO.OUT)


async def _run_pwm(cl, k, v):
    GPIO.setup(v.pin, GPIO.OUT)
    #   port = GPIO.PWM(v.pin, v.get("freq", 200))
    #   port.start(0)

    xover = False
    xval = 0
    val = 0

    dly = False
    lpct = -1

    def upd():
        nonlocal dly, lpct

        pct = xval if xover else val
        if lpct != pct:
            lpct = pct
            logger.info("Value: %s: %.3f", k, pct)
        if pct < 0.01:
            dly = False
        elif pct > 0.99:
            dly = True
        else:
            dly = pct / v.freq

    async def mon_flag(*, task_status):
        nonlocal xover
        async with cl.watch(v.override.flag, max_depth=0, fetch=True) as msgs:
            async for m in msgs:
                if m.get("state", "") == "uptodate":
                    task_status.started()
                    continue
                if "value" not in m:
                    continue
                xover = m.value
                upd()

    async def mon_pct(*, task_status):
        nonlocal xval
        async with cl.watch(v.override.val, max_depth=0, fetch=True) as msgs:
            async for m in msgs:
                if m.get("state", "") == "uptodate":
                    task_status.started()
                    continue
                if "value" not in m:
                    continue
                xval = m.value
                upd()

    async def mon_value(*, task_status):
        nonlocal val
        async with cl.watch(v.path, max_depth=0, fetch=True) as msgs:
            async for m in msgs:
                if m.get("state", "") == "uptodate":
                    task_status.started()
                    continue
                if "value" not in m:
                    continue
                val = m.value
                upd()

    async with anyio.create_task_group() as tg:
        GPIO.setup(v.pin, GPIO.OUT)
        GPIO.output(v.pin, False)
        inv = v.get("inverted", False)

        if "override" in v:
            await tg.start(mon_flag)
            await tg.start(mon_pct)
        await tg.start(mon_value)

        try:
            async for _ in t_iter(1 / v.freq):
                if dly is not False:
                    GPIO.output(v.pin, not inv)
                    if dly is True:
                        continue
                    await anyio.sleep(dly)
                GPIO.output(v.pin, inv)
        finally:
            GPIO.output(v.pin, inv)


@cli.command
@click.pass_obj
async def off(obj):
    "Emergency handler to turn the heat pump off in a controlled way."
    async with open_client(**mcfg.kv) as cl, anyio.create_task_group() as tg:
        d = Data(obj.cfg, cl)
        await tg.start(d.run_init)
        await d.off()
        tg.cancel_scope.cancel()


def vt(tau, ti, cf):
    if tau >= ti:
        return ti
    return ti + (cf.max - ti) * pow((ti - tau) / (ti - cf.min), 1 / cf.exp)


@cli.command
@click.pass_obj
async def curve(obj):
    "show the current heating curve"

    cf = obj.cfg.adj.curve

    for t in range(cf.min, cf.night.dest):
        print(f"{t:3d} {vt(t, cf.dest, cf):.1f} {vt(t, cf.night.dest, cf):.1f}")
