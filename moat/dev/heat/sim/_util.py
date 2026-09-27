"""Shared physics helpers for the plant simulator."""

from __future__ import annotations

import math

__all__ = ["C_WATER", "clamp", "kgps", "tank"]

C_WATER = 4.186
"""Specific heat of water, kJ/(kg·K). One litre of water is taken as 1 kg."""


def kgps(lpm: float) -> float:
    """Convert a flow in l/min to kg/s."""
    return lpm / 60


def clamp(v: float, lo: float, hi: float) -> float:
    """Restrict ``v`` to ``[lo, hi]``."""
    return lo if v < lo else min(v, hi)


def tank(
    t0: float,
    cap: float,
    fc: float,
    t_in: float,
    ua: float,
    t_amb: float,
    p: float,
    dt: float,
) -> tuple[float, float, float]:
    """
    Advance a well-mixed volume of water by ``dt`` seconds, exactly.

    The volume has heat capacity ``cap`` (kJ/K). Water enters at ``t_in``
    with capacity rate ``fc`` (kW/K, i.e. mass flow times c) and leaves
    at the tank's own temperature. ``ua`` (kW/K) couples it to ``t_amb``;
    ``p`` (kW) is added directly.

    Returns ``(t_new, t_avg, e_loss)``: the final temperature, the time
    average of the temperature over the interval (i.e. the effective
    temperature of the outflow, whose energy is ``fc * t_avg * dt``), and
    the energy lost to the surroundings (kJ).

    The ODE is linear, so this is energy-conserving for any ``dt``.
    """
    g = fc + ua
    if g <= 0:
        t1 = t0 + p * dt / cap
        return t1, (t0 + t1) / 2, 0.0
    t_eq = (fc * t_in + ua * t_amb + p) / g
    x = dt * g / cap
    if x < 1e-9:
        t1 = t0 + (t_eq - t0) * x
        t_avg = (t0 + t1) / 2
    else:
        e = math.exp(-x)
        t1 = t_eq + (t0 - t_eq) * e
        t_avg = t_eq + (t0 - t_eq) * (1 - e) / x
    return t1, t_avg, ua * (t_avg - t_amb) * dt
