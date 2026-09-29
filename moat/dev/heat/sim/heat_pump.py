"""Air/water heat pump and its circulation pump."""

from __future__ import annotations

import math
from enum import StrEnum

from ._util import C_WATER, clamp, kgps, tank

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import HeatPumpCfg, PumpCfg

__all__ = ["CircPump", "HeatPump", "Stage"]


class Stage(StrEnum):
    """Heat pump operating stage."""

    off = "off"
    delay = "delay"  # mode on, waiting for the compressor to start
    run = "run"
    deice = "deice"
    trip = "trip"  # over-temperature cutout, latched


class CircPump:
    """PWM-controlled circulation pump with dead zone and lag."""

    def __init__(self, cfg: PumpCfg) -> None:
        self.cfg = cfg
        self.flow = 0.0

    def target(self, pwm: float) -> float:
        """Steady-state flow (l/min) for a PWM value."""
        cfg = self.cfg
        if pwm <= cfg.dead:
            return 0.0
        f = cfg.flow_max * ((min(pwm, 1) - cfg.dead) / (1 - cfg.dead)) ** cfg.exp
        return max(f, cfg.flow_min)

    def step(self, dt: float, pwm: float, dead: bool = False) -> float:
        """Advance; returns the mean flow over the interval."""
        tgt = 0.0 if dead else self.target(pwm)
        f0 = self.flow
        if tgt == 0:
            # the pump stops, water stops quickly
            self.flow = 0.0
            return 0.0
        a = math.exp(-dt / self.cfg.tau)
        self.flow = tgt + (f0 - tgt) * a
        return (f0 + self.flow) / 2


class HeatPump:
    """
    Air/water heat pump: inflow pipe, condenser, compressor, de-icing.

    ``t_in`` is the temperature at the end of the supply pipe; ``t_out``
    that of the condenser. Without flow both drift towards the air temperature,
    and a running compressor overheats the condenser until the
    over-temperature trip latches.
    """

    def __init__(self, cfg: HeatPumpCfg, t_init: float) -> None:
        self.cfg = cfg
        self.stage = Stage.off
        self.t_stage = 0.0
        self.t_run = 0.0
        self.speed = 0.0
        self.ice = 0.0
        self.pipe = [t_init] * cfg.n_pipe  # supply segments; t_in is the last one
        self.ret = [t_init] * cfg.n_ret  # return segments
        self.t_out = t_init
        self.p_th = 0.0
        self.p_el = 0.0
        self.cop = 0.0
        self.errors: dict[str, int] = {}
        self.blocked = False  # an injected blocking error is present

    @property
    def t_in(self) -> float:
        """Temperature at the heat pump's inlet."""
        return self.pipe[-1]

    @property
    def energy(self) -> float:
        """Stored energy in pipes and condenser, kJ."""
        cfg = self.cfg
        return (
            cfg.cap_pipe * sum(self.pipe) / cfg.n_pipe
            + cfg.cap_ret * sum(self.ret) / cfg.n_ret
            + cfg.cap_hx * self.t_out
        )

    @staticmethod
    def _chain(
        seg: list[float], cap: float, ua: float, fc: float, t: float, amb: list[float], dt: float
    ) -> tuple[float, float]:
        """Pass water at ``t`` through a chain of segments. Returns (outflow temp, loss)."""
        n = len(seg)
        loss = 0.0
        for i in range(n):
            seg[i], t, lo = tank(seg[i], cap / n, fc, t, ua / n, amb[i], 0, dt)
            loss += lo
        return t, loss

    def _ambients(self, n: int, t_air: float, supply: bool) -> list[float]:
        """Per-segment surroundings: indoors near the buffer, outdoors near the unit."""
        cfg = self.cfg
        n_out = round(n * cfg.outdoor)
        amb = [cfg.t_room] * (n - n_out) + [t_air] * n_out
        return amb if supply else amb[::-1]

    def p_max(self, t_air: float) -> float:
        """Thermal output at full speed."""
        cfg = self.cfg
        return max(0.0, cfg.p_nom * (1 + cfg.p_slope * (t_air - cfg.t_ref)))

    def cop_at(self, t_out: float, t_air: float) -> float:
        """Coefficient of performance for the given temperatures."""
        cfg = self.cfg
        th = t_out + cfg.lift_hot + 273.15
        tc = t_air - cfg.lift_cold + 273.15
        if th - tc < 1:
            return cfg.cop_max
        return clamp(cfg.eta * th / (th - tc), cfg.cop_min, cfg.cop_max)

    def _goto(self, stage: Stage, now: float) -> None:
        self.stage = stage
        self.t_stage = now

    def step(
        self,
        dt: float,
        now: float,
        *,
        mode: int,
        load: float,
        flow: float,
        t_ret: float,
        t_air: float,
        rh: float,
    ) -> tuple[float, float, float]:
        """
        Advance by ``dt``.

        ``flow`` (l/min) passes the heat pump, entering at ``t_ret``.
        Returns ``(t_supply, e_th, e_loss)``: the effective temperature of
        the water leaving the condenser during this step, the thermal
        energy added (negative while de-icing), and the energy lost to
        the air (kJ).
        """
        cfg = self.cfg
        on = mode != cfg.mode_off and load >= cfg.min_load and not self.blocked
        st = self.stage

        if st == Stage.trip:
            if (
                not on
                and self.t_out < cfg.trip_out - cfg.trip_reset
                and self.t_in < cfg.trip_in - cfg.trip_reset
            ):
                self.errors.pop(cfg.trip_path, None)
                self._goto(Stage.off, now)
        elif st == Stage.deice:
            if now - self.t_stage >= cfg.deice_time:
                self.ice = 0.0
                self._goto(Stage.delay if on else Stage.off, now)
        elif st == Stage.off:
            if on:
                self._goto(Stage.delay, now)
        elif st == Stage.delay:
            if not on:
                self._goto(Stage.off, now)
            elif now - self.t_stage >= cfg.start_delay:
                self._goto(Stage.run, now)
                self.t_run = now
        elif st == Stage.run:
            if not on:
                self._goto(Stage.off, now)
            elif self.ice >= 1:
                self._goto(Stage.deice, now)

        st = self.stage
        if st == Stage.run:
            tgt = clamp(max(load, cfg.min_mod), 0, 1)
            if now - self.t_run < cfg.warmup:
                tgt = max(tgt, cfg.start_speed)
            if self.speed < cfg.min_mod:
                self.speed = min(tgt, cfg.min_mod)
            dv = cfg.ramp * dt
            self.speed = clamp(tgt, self.speed - dv, self.speed + dv)
            self.cop = self.cop_at(self.t_out, t_air)
            self.p_th = self.speed * self.p_max(t_air)
            self.p_el = self.p_th / self.cop + cfg.aux

            if t_air < cfg.ice_t_max and rh > cfg.ice_rh_min:
                f_t = min(1.0, (cfg.ice_t_max - t_air) / cfg.ice_t_span)
                f_rh = (rh - cfg.ice_rh_min) / (1 - cfg.ice_rh_min)
                self.ice += dt * self.speed * f_t * f_rh / cfg.ice_time
        elif st == Stage.deice:
            self.speed = 0.0
            self.p_th = -cfg.deice_power
            self.p_el = cfg.deice_el
        else:
            self.speed = 0.0
            self.p_th = 0.0
            self.p_el = cfg.aux if st == Stage.delay else cfg.standby

        e_th = self.p_th * dt
        fc = kgps(flow) * C_WATER
        # heat leaking between the two sensor positions inside the unit
        q = cfg.k_bleed * (self.pipe[-1] - self.t_out) * dt
        self.pipe[-1] -= q / (cfg.cap_pipe / cfg.n_pipe)
        self.t_out += q / cfg.cap_hx

        amb = self._ambients(cfg.n_pipe, t_air, True)
        t_in_avg, loss_p = self._chain(self.pipe, cfg.cap_pipe, cfg.ua_pipe, fc, t_ret, amb, dt)
        self.t_out, t_hx, loss_h = tank(
            self.t_out, cfg.cap_hx, fc, t_in_avg, cfg.ua_hx, t_air, self.p_th, dt
        )
        amb = self._ambients(cfg.n_ret, t_air, False)
        t_sup, loss_r = self._chain(self.ret, cfg.cap_ret, cfg.ua_ret, fc, t_hx, amb, dt)
        loss_h += loss_r

        if st in (Stage.run, Stage.delay) and (
            self.t_out > cfg.trip_out or self.t_in > cfg.trip_in
        ):
            self.errors[cfg.trip_path] = (
                cfg.trip_code_out if self.t_out > cfg.trip_out else cfg.trip_code_in
            )
            self.speed = 0.0
            self._goto(Stage.trip, now)

        return t_sup, e_th, loss_p + loss_h
