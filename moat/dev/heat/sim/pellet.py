"""KWB pellet burner with boiler water and charging pump."""

from __future__ import annotations

import math

from ._util import C_WATER, clamp, kgps, tank

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import PelletCfg

__all__ = ["Pellet"]


class Pellet:
    """
    Pellet burner, modelled as a state-code sequence driving the fire.

    ``off`` → ``prepare`` → ``ignite`` → ``run``; ``run`` burns out
    (``burnout`` → ``afterrun``) when the burner is switched off or the
    boiler exceeds its goal temperature, then goes to ``off`` or
    ``standby``. A failed ignition retries ``ignite_retries`` times, then
    latches ``fault`` until the burner is switched off.

    The charging pump moves boiler water into the buffer once the boiler
    is hotter than the pump goal (the "startup patch" goal of the legacy
    controller) and than the buffer return. Its return-flow raise valve
    then throttles the buffer flow to keep the boiler near that goal.
    """

    def __init__(self, cfg: PelletCfg) -> None:
        self.cfg = cfg
        self.code = cfg.codes.off
        self.t_code = 0.0
        self.fire = 0.0
        self.temp = cfg.t_init
        self.pump = False
        self.fail_next = 0  # number of upcoming ignitions that fail
        self._tries = 0

    @property
    def energy(self) -> float:
        """Stored energy in the boiler, kJ."""
        return self.cfg.cap * self.temp

    def _goto(self, code: int, now: float) -> None:
        self.code = code
        self.t_code = now

    def step(
        self,
        dt: float,
        now: float,
        *,
        run: bool,
        load: float,
        goal: float,
        pump_goal: float | None,
        t_ret: float,
    ) -> tuple[float, float, float, float]:
        """
        Advance by ``dt``.

        Returns ``(flow, t_supply, e_fire, e_loss)``: the charging flow
        (l/min) and effective supply temperature, the heat released by
        the fire, and the loss to the room (kJ).
        """
        cfg = self.cfg
        c = cfg.codes
        age = now - self.t_code
        code = self.code

        if code == c.off:
            if run:
                self._tries = 0
                self._goto(c.prepare, now)
        elif code == c.prepare:
            if not run:
                self._goto(c.off, now)
            elif age >= cfg.t_prepare:
                self._goto(c.ignite, now)
        elif code == c.ignite:
            if not run:
                self._goto(c.burnout, now)
            elif age >= cfg.t_ignite:
                if self.fail_next > 0:
                    self.fail_next -= 1
                    self._tries += 1
                    self._goto(c.prepare if self._tries <= cfg.ignite_retries else c.fault, now)
                    self.fire = 0.0
                else:
                    self._goto(c.run, now)
        elif code == c.run:
            if not run or self.temp > goal + cfg.hyst_off:
                self._goto(c.burnout, now)
        elif code == c.burnout:
            if age >= cfg.t_burnout:
                self._goto(c.afterrun, now)
        elif code == c.afterrun:
            if age >= cfg.t_afterrun:
                self._goto(c.standby if run else c.off, now)
        elif code == c.standby:
            if not run:
                self._goto(c.off, now)
            elif self.temp < goal - cfg.hyst_on:
                self._tries = 0
                self._goto(c.prepare, now)
        elif code == c.fault:
            if not run:
                self._goto(c.off, now)

        code = self.code
        age = now - self.t_code
        p_min = cfg.min_mod * cfg.p_nom
        if code == c.ignite:
            self.fire = p_min * min(1.0, age / cfg.t_ignite)
        elif code == c.run:
            tgt = cfg.p_nom * clamp(load, cfg.min_mod, 1)
            dv = cfg.ramp * dt
            self.fire = clamp(tgt, self.fire - dv, self.fire + dv)
        elif code == c.burnout:
            self.fire *= math.exp(-dt * 4 / cfg.t_burnout)
        else:
            self.fire = 0.0

        on_at = cfg.pump_on if pump_goal is None else pump_goal
        if self.pump:
            self.pump = self.temp >= on_at - cfg.pump_hyst and self.temp > t_ret
        else:
            self.pump = self.temp >= on_at and self.temp > t_ret + cfg.pump_min_delta
        # return-flow raise: the mixing valve keeps the boiler near the goal
        flow = (
            cfg.flow * clamp((self.temp - on_at) / cfg.pump_hyst + 1, 0, 1) if self.pump else 0.0
        )

        e_fire = self.fire * dt
        self.temp, t_sup, loss = tank(
            self.temp, cfg.cap, kgps(flow) * C_WATER, t_ret, cfg.ua, cfg.t_amb, self.fire, dt
        )
        return flow, t_sup, e_fire, loss
