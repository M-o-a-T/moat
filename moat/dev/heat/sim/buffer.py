"""Stratified buffer tank."""

from __future__ import annotations

from ._util import C_WATER

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import BufferCfg

__all__ = ["Buffer"]


class Buffer:
    """
    A stack of equal, well-mixed layers; index 0 is the top.

    Flows are plug flows between an inlet and an outlet layer (upwind,
    conservative). Buoyancy is restored after each step by mixing
    inverted layers; conduction and losses act between layers and to
    the room.
    """

    def __init__(self, cfg: BufferCfg) -> None:
        self.cfg = cfg
        self.n = n = cfg.layers
        self.mass = cfg.volume / n
        t_top, t_bot = cfg.t_init
        self.t = [t_top + (t_bot - t_top) * i / max(n - 1, 1) for i in range(n)]

    def layer(self, frac: float) -> int:
        """Index of the layer at relative height ``frac`` (0 = top, 1 = bottom)."""
        return min(self.n - 1, max(0, int(frac * self.n)))

    def temp(self, frac: float) -> float:
        """Temperature at relative height ``frac``."""
        return self.t[self.layer(frac)]

    @property
    def energy(self) -> float:
        """Stored energy relative to 0 °C, kJ."""
        return self.mass * C_WATER * sum(self.t)

    def flow(self, m: float, t_in: float, enter: int, leave: int) -> float:
        """
        Move ``m`` kg of water through the tank.

        Water at ``t_in`` enters at layer ``enter``; the same mass leaves
        at layer ``leave``, and the layers in between shift. Returns the
        temperature of the water that left, which is that of layer
        ``leave`` before the call.

        ``m`` must not exceed one layer's mass.
        """
        t = self.t
        t_out = t[leave]
        if m <= 0:
            return t_out
        f = m / self.mass
        if f > 1 + 1e-9:
            raise ValueError(f"Flow {m} kg exceeds layer mass {self.mass}")
        if enter < leave:  # downwards
            for i in range(leave, enter, -1):
                t[i] += f * (t[i - 1] - t[i])
        elif enter > leave:  # upwards
            for i in range(leave, enter):
                t[i] += f * (t[i + 1] - t[i])
        t[enter] += f * (t_in - t[enter])
        return t_out

    def relax(self, dt: float) -> float:
        """Conduction between layers and losses to the room. Returns the loss, kJ."""
        cfg = self.cfg
        t = self.t
        n = self.n
        cap = self.mass * C_WATER
        k = cfg.k_cond * dt / cap
        if k:
            flux = [k * (t[i] - t[i + 1]) for i in range(n - 1)]
            for i, q in enumerate(flux):
                t[i] -= q
                t[i + 1] += q
        ua = cfg.ua / n
        loss = 0.0
        for i in range(n):
            q = ua * (t[i] - cfg.t_amb) * dt
            t[i] -= q / cap
            loss += q
        return loss

    def mix(self) -> None:
        """Mix inverted layers (warmer water below colder) until the stack is stable."""
        t = self.t
        if all(t[i] >= t[i + 1] for i in range(self.n - 1)):
            return
        # pool adjacent violators: blocks of (sum, count), means non-increasing
        blocks: list[list[float]] = []
        for v in t:
            blocks.append([v, 1])
            while len(blocks) > 1 and (
                blocks[-2][0] / blocks[-2][1] < blocks[-1][0] / blocks[-1][1]
            ):
                s, c = blocks.pop()
                blocks[-1][0] += s
                blocks[-1][1] += c
        i = 0
        for s, c in blocks:
            v = s / c
            for _ in range(int(c)):
                t[i] = v
                i += 1
