"""
PID controller library
"""

# Created on Wed Jun 22 20:06:38 2022
#
# @author: eadali

from __future__ import annotations

from math import exp

from moat.util import attrdict
from moat.util.compat import ticks_diff

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

try:
    # MicroPython. Use milliseconds.
    from time import ticks_ms as time  # pyright:ignore[reportAttributeAccessIssue]

    PID_TC = 1000
    MAX_VAL = 2**31 - 1

except ImportError:
    # Standard Python
    from time import monotonic as time

    PID_TC = 1
    MAX_VAL = float("inf")


class PID:
    """An advanced PID controller with first-order filter on derivative term.

    Parameters
    ----------
    Kp: float
        Proportional gain.
    Ki: float
        Integral time constant.
    Kd: float
        Derivative time constant.
    Tf: float
        Time constant of the first-order derivative filter.

    """

    t: float | None  # current time
    e: float | None  # current error
    i: float  # current integral

    Kp: float  # proportional gain
    Ki: float | None  # integral gain
    Kd: float | None  # differential gain
    Tf: float | None  # time constant for derivative filter

    lower: float  # lower output limit
    upper: float  # upper output limit

    def __init__(
        self,
        Kp: float | None = None,
        Ki: float | None = None,
        Kd: float | None = None,
        Tf: float | None = None,
        t: float | None = None,
    ):
        """
        Setup. Legacy call, using gain constants, not times, for the i and d terms.
        """
        self.set_gains(Kp, Ki, Kd, Tf)
        self.set_output_limits()
        self.reset(t)

    def reset(self, t: float | None = None):  # noqa: D102
        self.set_state(t, None, None)

    def __call__(self, e: float, t: float | None = None) -> float:
        """Run a PID step.

        Args:
            e: Error signal.
            t: Current time.

        Returns:
            Control signal.

        """
        return self.sum(self.integrate(e, t))

    def sum(self, args: Sequence[float]) -> float:
        "Sum the values and apply limit"
        return min(max(sum(args), self.lower), self.upper)

    def get_gains(self) -> tuple[float, float | None, float | None, float | None]:
        """Get PID controller gains.

        Returns
        -------
        tuple
            Gains of PID controller (Kp, Ki, Kd, Tf).

        """
        return (
            self.Kp,
            self.Ki * PID_TC if self.Ki else None,
            self.Kd / PID_TC if self.Kd else None,
            self.Tf / PID_TC if self.Tf else None,
        )

    def set_gains(
        self, Kp: float | None, Ki: float | None, Kd: float | None, Tf: float | None = None
    ):
        """Set PID controller gains.

        Args:
            Kp: Proportional gain.
            Ki: Integral gain.
            Kd: Derivative gain.
            Tf: Time constant of the first-order derivative filter.

        """
        self.Kp = Kp or 0
        self.Ki = Ki / PID_TC if Ki else None
        self.Kd = Kd * PID_TC if Kd else None
        self.Tf = Tf * PID_TC if Tf else None

    def set_output_limits(self, lower: float | None = -MAX_VAL, upper: float | None = MAX_VAL):
        """Set PID controller output limits for anti-windup.

        Parameters
        ----------
        lower : float or None
            Lower limit for anti-windup,
        upper : flaot or None
            Upper limit for anti-windup.

        """
        self.lower = -MAX_VAL if lower is None else lower
        self.upper = +MAX_VAL if upper is None else upper

    def get_output_limits(self) -> tuple[float, float]:
        """Get PID controller output limits for anti-windup.

        Return:
            Output limits (lower, upper).

        """
        return self.lower, self.upper

    def set_state(
        self, t: float | None = None, e: float | None = None, i: float | None = None
    ) -> None:
        """Set PID controller states.

        Args:
            t0:
                Current time. If ``None``, calls `time`.
            e0:
                Current error.
            i0:
                Current integral.

        """
        if t is None:
            t = time()
        self.t = t
        self.e = e
        self.i = i or 0

    def get_state(self) -> tuple[float | None, float | None, float]:
        """Get PID controller states.

        Returns:
            State of the PID controller (t0, e0, i0)

        """
        return self.t, self.e, self.i

    def integrate(self, e: float, t: float | None = None) -> tuple[float, float, float]:
        """Calculates PID controller output.

        Args:
            e: Error signal.
            t: Current time.

        Returns:
            p,i,d: Control signal (in parts), *not* limited.

        """
        t0, e0, i0 = self.get_state()
        if t is None:
            t = time()

        # Check timestamp
        if t0 is None:
            t0 = t
        elif t0 > t:
            raise ValueError("Time went backwards")

        if e0 is None:
            e0 = e
        # Calculate time step
        dt = ticks_diff(t, t0)
        # Calculate proportional term
        p = self.Kp * e
        # Calculate integral term
        if self.Ki:
            i = i0 + dt * self.Ki * e
            # anti-windup
            i = min(max(i, self.lower - p), self.upper - p)
        else:
            i = 0
        # Calculate derivative term
        d = 0.0
        if dt and (Kd := self.Kd):
            if (Tf := self.Tf) is not None:
                Tdf = Tf / Kd
                x = -e0 / Tdf
                ex = exp(-dt / Tf)
                y = ex * x - (1.0 - ex) / Tdf * e
                d = y + e / Tdf
                e = -Tdf * y
            else:
                d = (e - e0) * Kd / dt
        # Set initial value for next cycle
        self.set_state(t, e, i)

        return p, i, d


class CPID(PID):
    """
    A PID that's configured::

        flow:
            p: 0.1
            i: 0.01
            d: 0.0
            tf: 0.0  # both must be set

            # output limits
            min: .3
            max: .95

            # setpoint change: adjust integral for best guess
            # input 20, output .8 == 20/.8
            factor: .04
            offset: 0

            state: foo
    """

    def __init__(self, cfg: attrdict, state: attrdict | None = None, t: float | None = None):
        """
        @cfg: our configuration. See above.
        @state: the state storage. Ours is at ``state[cfg.state]``.
        """
        super().__init__(cfg.p, cfg.i, cfg.d, cfg.tf)
        self.cfg = cfg
        self.set_output_limits(self.cfg.get("min", None), self.cfg.get("max", None))

        if state is None:
            state = attrdict()
        self.state = state
        self.set_state(state.get("t", t or time()), state.get("e", 0), state.get("i", 0))
        state.setdefault("setpoint", None)

    def setpoint(self, setpoint: float):
        """
        Adjust the setpoint.
        """
        if self.state.setpoint == setpoint:
            return
        i = self.i
        if i is None:
            i = 0
        osp = self.state.setpoint
        if osp is not None:
            i -= osp * self.cfg.get("factor", 0) + self.cfg.get("offset", 0)
        self.state.setpoint = nsp = setpoint
        i += nsp * self.cfg.get("factor", 0) + self.cfg.get("offset", 0)
        self.i = i

    def move_to(self, i: float, o: float, t=None):
        """
        Tell the controller that this input shall result in that output.
        """
        if t is None:
            t = time()
        self.t = t
        if self.state.setpoint is not None:
            i -= self.state.setpoint
            self.i = o + i * self.Kp
            self.e = i

    def __call__(self, i: float, t: float | None = None) -> float:
        """
        Run a PID step.

        Args:
            i: the current output.
            t: current time, or `None` for monotonicity.
        Returns:
            the new input.
        """
        if t is None:
            t = time()
        res = super()(e=self.state.setpoint - i, t=t)
        self._update_state()
        return res

    def integrate(self, i, t=None) -> tuple[float, float, float]:  # pyright:ignore
        """
        Run a PID step.

        Args:
            i: the current output.
            t: current time, or `None` for monotonicity.
        Returns:
            the p,i,d control variables.
            Call :meth:`sum` to get the new input.
        """
        if t is None:
            t = time()
        res = super().integrate(e=self.state.setpoint - i, t=t)
        self._update_state()
        return res

    def _update_state(self):
        _t, e, i = self.get_state()
        self.state.e = e
        self.state.i = i
