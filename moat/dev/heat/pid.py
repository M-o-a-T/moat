"""
PID controllers for the heat controller's unit cores.

`APID` wraps :class:`moat.lib.pid.CPID`: its input is the current
measurement, not the error. It runs on monotonic time and keeps its state
in a `PIDState`, which lives inside the owning unit's
:class:`~moat.dev.heat.state.State`. See HEAT.md §2.3.
"""

from __future__ import annotations

from pydantic import ValidationInfo, field_serializer, field_validator

from moat.util import attrdict
from moat.lib.config.base import BaseModel
from moat.lib.path import Path  # noqa: TC002  # pydantic needs it at runtime
from moat.lib.pid import CPID

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import SerializationInfo

__all__ = ["APID", "T_OFFSET", "PIDCfg", "PIDLog", "PIDState"]

T_OFFSET = "t_offset"
"""
The validation and serialisation context key for the difference between
wall-clock and monotonic time. :class:`~moat.dev.heat.state.StateStore`
sets it so that the ``t`` field of a `PIDState` is persisted as
wall-clock time.
"""


class PIDLog(BaseModel):
    """Where a PID publishes its values."""

    value: Path | None = None
    """Path for the PID's output."""

    setpoint: Path | None = None
    """Path for the PID's setpoint."""


class PIDCfg(BaseModel):
    """
    Configuration of one PID controller.

    The gains and limits are those of :class:`moat.lib.pid.CPID`.
    """

    p: float = 0
    i: float = 0
    d: float = 0
    tf: float = 0
    min: float | None = None
    max: float | None = None
    factor: float = 0
    offset: float = 0

    log: PIDLog = PIDLog()
    """Where to publish output and setpoint."""

    rebase_after: float = 300
    """
    A persisted state older than this (in seconds) is treated as current,
    so the first step after an outage doesn't integrate over it.
    """


class PIDState(BaseModel):
    """
    Persistent state of one PID controller.

    In memory, ``t`` is monotonic time. When serialised or validated with a
    `T_OFFSET` context it is converted to / from wall-clock time.
    """

    i: float = 0
    e: float = 0
    setpoint: float | None = None
    t: float | None = None

    @field_serializer("t")
    def _ser_t(self, t: float | None, info: SerializationInfo) -> float | None:
        off = (info.context or {}).get(T_OFFSET)
        if t is None or off is None:
            return t
        return t + off

    @field_validator("t")
    @classmethod
    def _val_t(cls, t: float | None, info: ValidationInfo) -> float | None:
        off = (info.context or {}).get(T_OFFSET)
        if t is None or off is None:
            return t
        return t - off


class APID:
    """
    A PID controller with persistable state and value logging.

    Args:
        cfg: The controller's configuration.
        state: The controller's state; updated in place.
        now: The current monotonic time.
    """

    def __init__(self, cfg: PIDCfg, state: PIDState, now: float) -> None:
        self.state = state
        self.logs: dict[Path, float] = {}
        """Values to publish, by path. The owner writes and clears them."""

        t = state.t
        if t is None or not 0 <= now - t <= cfg.rebase_after:
            t = now
        self._st = attrdict(e=state.e, i=state.i, setpoint=state.setpoint)
        self.pid = CPID(self._pid_cfg(cfg), self._st, t=t)
        self.pid.set_state(t=t)
        self.cfg = cfg
        self._sync()

    @staticmethod
    def _pid_cfg(cfg: PIDCfg) -> attrdict:
        return attrdict(cfg.model_dump(exclude={"log", "rebase_after"}))

    def _sync(self) -> None:
        t, e, i = self.pid.get_state()
        self.state.t = t
        self.state.e = e if e is not None else 0
        self.state.i = i
        self.state.setpoint = self._st.setpoint

    def _log(self, path: Path | None, value: float) -> None:
        if path is not None:
            self.logs[path] = value

    def update_cfg(self, cfg: PIDCfg) -> None:
        """Apply a changed configuration without a bump."""
        self.cfg = cfg
        self.pid.cfg = self._pid_cfg(cfg)
        self.pid.cfg_updated()
        self._sync()

    def setpoint(self, setpoint: float) -> None:
        """Change the setpoint."""
        self.pid.setpoint(setpoint)
        self._sync()
        self._log(self.cfg.log.setpoint, setpoint)

    def __call__(self, value: float, now: float) -> float:
        """
        Run a step.

        Args:
            value: The current measurement.
            now: The current monotonic time.

        Returns:
            The new output.
        """
        # Not ``self.pid(value, t=now)``: see moat-vou.
        return self.sum(self.integrate(value, now))

    def integrate(self, value: float, now: float) -> tuple[float, float, float]:
        """
        Run a step and return the P, I and D parts, not limited.

        Call :meth:`sum` to get the output.
        """
        res = self.pid.integrate(value, t=now)
        self._sync()
        return res

    def sum(self, pid: tuple[float, float, float]) -> float:
        """The output for the given P, I and D parts."""
        res = self.pid.sum(pid)
        self._log(self.cfg.log.value, res)
        return res

    def move_to(self, value: float, out: float, now: float) -> None:
        """Change the state so that this measurement results in that output."""
        self.pid.move_to(value, out, t=now)
        self._sync()
