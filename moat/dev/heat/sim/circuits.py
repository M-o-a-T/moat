"""Heat consumers: heating circuit with house, and the fresh-water station."""

from __future__ import annotations

import math

from ._util import C_WATER, kgps, tank

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import DhwCfg, HeatingCfg

__all__ = ["Dhw", "Heating"]


class Heating:
    """
    Heating circuit: mixing valve, radiators, and a one-node house.

    The mixing valve limits the supply to the flow setpoint; the buffer
    supplies only the hot share of the circuit flow, the rest is
    recirculated return water.
    """

    def __init__(self, cfg: HeatingCfg) -> None:
        self.cfg = cfg
        self.t_room = cfg.t_room
        self.t_supply = cfg.t_room  # sensor value, lagging
        self.q = 0.0  # radiator output, kW

    def step(
        self, dt: float, *, on: bool, setpoint: float, t_tap: float, t_air: float
    ) -> tuple[float, float]:
        """
        Advance by ``dt``.

        Returns ``(m_buffer, t_return)``: the mass drawn from the buffer at
        ``t_tap`` (kg) and the temperature it is returned at. The energy
        taken is ``m_buffer * c * (t_tap - t_return)``.
        """
        cfg = self.cfg
        m = 0.0
        t_ret = t_tap
        t_s = self.t_room
        self.q = 0.0
        if on:
            t_s = min(t_tap, setpoint)
            fc = kgps(cfg.flow) * C_WATER
            dt_rad = t_s - self.t_room
            if dt_rad > 0 and fc > 0:
                q = min(cfg.k_rad * dt_rad**cfg.n_rad, fc * dt_rad)
                t_ret = t_s - q / fc
                if t_tap - t_ret > 0.01:
                    m = kgps(cfg.flow) * dt * (t_s - t_ret) / (t_tap - t_ret)
                    self.q = m * C_WATER * (t_tap - t_ret) / dt

        self.t_room, _, _ = tank(self.t_room, cfg.cap_house, 0, 0, cfg.ua_house, t_air, self.q, dt)
        a = math.exp(-dt / cfg.sensor_tau)
        self.t_supply = t_s + (self.t_supply - t_s) * a
        return m, t_ret


class Dhw:
    """
    Fresh-water station: domestic hot water is heated from the buffer top.

    Draws are scheduled events. If the buffer top is too cold, the tap
    temperature drops accordingly.
    """

    def __init__(self, cfg: DhwCfg) -> None:
        self.cfg = cfg
        self.events: list[tuple[float, float, float]] = []  # start, end, l/min
        self.lpm = 0.0
        self.t_tap = cfg.t_cold

    def add(self, start: float, duration: float, lpm: float) -> None:
        """Schedule a draw."""
        self.events.append((start, start + duration, lpm))
        self.events.sort()

    def add_daily(self, day_start: float, day_offset: float) -> None:
        """Schedule the configured daily draws for the day starting at ``day_start``."""
        for hour, dur, lpm in self.cfg.daily:
            self.add(day_start + hour * 3600 - day_offset, dur, lpm)

    def demand(self, now: float) -> float:
        """Current draw, l/min."""
        while self.events and self.events[0][1] <= now:
            self.events.pop(0)
        return sum(lpm for s, e, lpm in self.events if s <= now < e)

    def step(self, dt: float, now: float, t_top: float) -> tuple[float, float]:
        """
        Advance by ``dt``.

        Returns ``(m_buffer, t_return)`` like :meth:`Heating.step`.
        """
        cfg = self.cfg
        self.lpm = lpm = self.demand(now)
        if not lpm:
            self.t_tap = cfg.t_cold
            return 0.0, t_top
        t_ret = cfg.t_cold + cfg.approach
        t_tap = max(cfg.t_cold, min(cfg.t_hot, t_top - cfg.min_delta))
        if t_top <= t_ret:
            self.t_tap = cfg.t_cold
            return 0.0, t_top
        q = kgps(lpm) * C_WATER * (t_tap - cfg.t_cold)
        m = q * dt / (C_WATER * (t_top - t_ret))
        m_max = kgps(cfg.primary_max) * dt
        if m > m_max:
            m = m_max
            t_tap = cfg.t_cold + m * (t_top - t_ret) / (kgps(lpm) * dt)
        self.t_tap = t_tap
        return m, t_ret
