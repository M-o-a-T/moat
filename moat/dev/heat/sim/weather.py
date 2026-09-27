"""Outside air: temperature, humidity, forecast."""

from __future__ import annotations

import math
from bisect import bisect_right

from ._util import clamp

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from random import Random

    from .config import WeatherCfg

__all__ = ["Weather"]


class Weather:
    """
    Deterministic weather.

    The base temperature is a daily sine (coldest at ``t_min_hour``) or
    a piecewise-linear profile; seeded AR(1) noise is added on top.
    The forecast minimum uses the base curve plus the decaying current
    noise, i.e. a forecaster who knows the climate but not the weather.
    """

    def __init__(self, cfg: WeatherCfg, rng: Random, day_offset: float = 0) -> None:
        self.cfg = cfg
        self.rng = rng
        self.day_offset = day_offset
        self.noise = 0.0
        self.offset = 0.0  # added by tests to shift the weather
        self.t_air = 0.0
        self.rh = cfg.rh_mean
        self._update(0.0)

    def _phase(self, now: float) -> float:
        h = ((now + self.day_offset) / 3600 - self.cfg.t_min_hour) % 24
        return -math.cos(2 * math.pi * h / 24)  # -1 at the coldest hour

    def base(self, now: float) -> float:
        """Temperature without noise."""
        cfg = self.cfg
        if cfg.profile:
            pts = cfg.profile
            if now <= pts[0][0]:
                return pts[0][1] + self.offset
            if now >= pts[-1][0]:
                return pts[-1][1] + self.offset
            i = bisect_right([p[0] for p in pts], now)
            (t0, v0), (t1, v1) = pts[i - 1], pts[i]
            return v0 + (v1 - v0) * (now - t0) / (t1 - t0) + self.offset
        return cfg.mean + cfg.amp * self._phase(now) + self.offset

    def _update(self, now: float) -> None:
        cfg = self.cfg
        self.t_air = self.base(now) + self.noise
        self.rh = clamp(cfg.rh_mean - cfg.rh_amp * self._phase(now), 0, 1)

    def step(self, dt: float, now: float) -> None:
        """Advance to ``now`` (the end of a step of length ``dt``)."""
        cfg = self.cfg
        if cfg.sigma:
            a = math.exp(-dt / cfg.tau)
            self.noise = self.noise * a + cfg.sigma * math.sqrt(1 - a * a) * self.rng.gauss(0, 1)
        self._update(now)

    def forecast_min(self, now: float) -> float:
        """Minimum temperature expected over the forecast horizon."""
        cfg = self.cfg
        res = self.t_air
        t = cfg.forecast_step
        while t <= cfg.forecast_horizon:
            v = self.base(now + t) + self.noise * math.exp(-t / cfg.tau)
            res = min(res, v)
            t += cfg.forecast_step
        return res
