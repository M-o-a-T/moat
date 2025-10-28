"""
PID controller library
"""

# Created on Wed Jun 22 20:06:38 2022
#
# @author: eadali

from __future__ import annotations

from math import exp
from time import monotonic as time

from moat.util import attrdict

PID_TC = 1


class PID:
    """An advanced PID controller with first-order filter on derivative term.

    Parameters
    ----------
    Kp : float
        Proportional gain.
    Ki: float
        Integral gain.
    Kd : float
        Derivative gain.
    Tf : float
        Time constant of the first-order derivative filter.

    """

    t: int | float | None  # current time
    e: float | None  # current error
    i: float  # current integral

    Kp: float  # proportional gain
    Ki: float  # integral gain
    Kd: float  # differential gain
    Tf: float | None  # time constant for derivative filter

    def __init__(
        self, Kp: float, Ki: float, Kd: float, Tf: float | None = None, t: float | None = None
    ):
        self.set_gains(Kp, Ki, Kd, Tf)
        self.set_output_limits(None, None)
        self.reset(t)

    def reset(self, t: float | None = None):  # noqa: D102
        self.set_state(t, None, None)

    def __call__(self, e: float, t: float | None = None):
        """Run a PID step.

        Args:
            e: Error signal.
            t: Current time.

        Returns:
            Control signal.

        """
        return self.sum(self.integrate(e, t))

    def sum(self, args):
        "Sum the values and apply limit"
        return min(max(sum(args), self.lower), self.upper)

    def set_gains(self, Kp: float, Ki: float, Kd: float, Tf: float | None = None):
        """Set PID controller gains.

        Args:
            Kp: Proportional gain.
            Ki: Integral gain.
            Kd: Derivative gain.
            Tf: Time constant of the first-order derivative filter.

        """
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.Tf = Tf or None  # if zero

    def get_gains(self) -> tuple[float, float, float, float | None]:
        """Get PID controller gains.

        Returns
        -------
        tuple
            Gains of PID controller (Kp, Ki, Kd, Tf).

        """
        return self.Kp, self.Ki, self.Kd, self.Tf

    def set_output_limits(self, lower, upper):
        """Set PID controller output limits for anti-windup.

        Parameters
        ----------
        lower : float or None
            Lower limit for anti-windup,
        upper : flaot or None
            Upper limit for anti-windup.

        """
        self.lower, self.upper = lower, upper
        if lower is None:
            self.lower = -float("inf")
        if upper is None:
            self.upper = +float("inf")

    def get_output_limits(self) -> tuple[float, float]:
        """Get PID controller output limits for anti-windup.

        Return:
            Output limits (lower, upper).

        """
        return self.lower, self.upper

    def set_state(self, t: float | None = None, e: float | None = None, i: float = 0) -> None:
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

    def get_state(self) -> tuple[int | float, float]:
        """Get PID controller states.

        Returns:
            State of the PID controller (t0, e0, i0)

        """
        return self.t, self.e, self.i

    def __set_none_value(self, t, e):
        """Set None states for first cycle."""
        t0, e0, i0 = self.get_state()
        if t0 is None:
            if t is None:
                t = time()
            t0 = t
        if e0 is None:
            e0 = e
        if i0 is None:
            i0 = 0.0
        self.set_state(t0, e0, i0)

    def integrate(self, e: float, t: float | None = None):
        """Calculates PID controller output.

        Args:
            e: Error signal.
            t: Current time.

        Returns:
            p,i,d: Control signal (in parts), *not* limited.

        """
        t0, e0, i0 = self.get_state()

        # Check timestamp
        if t0 is None:
            t0 = t
        elif t0 > t:
            raise ValueError("Time went backwards")

        if e0 is None:
            e0 = e
        # Calculate time step
        dt = t - t0
        # Calculate proportional term
        p = self.Kp * e
        # Calculate integral term
        i = i0 + dt * self.Ki * e
        # anti-windup
        i = min(max(i, self.lower - p), self.upper - p)
        # Calculate derivative term
        d = 0.0
        if self.Kd and dt:
            if self.Tf is not None:
                Kn = 1.0 / self.Tf
                x = -Kn * self.Kd * e0
                x = exp(-Kn * dt) * x - Kn * (1.0 - exp(-Kn * dt)) * self.Kd * e
                d = x + Kn * self.Kd * e
                e = -(self.Tf / self.Kd) * x
            else:
                d = self.Kd * (e - e0) / dt
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

    def __init__(self, cfg, state=None, t=None):
        """
        @cfg: our configuration. See above.
        @state: the state storage. Ours is at ``state[cfg.state]``.
        """
        super().__init__(cfg.p, cfg.i, cfg.d, cfg.tf)
        self.cfg = cfg
        self.set_output_limits(self.cfg.get("min", None), self.cfg.get("max", None))

        if "state" in cfg and state is not None:
            s = state.setdefault(cfg.state, attrdict())
        else:
            s = attrdict()
        self.state = s
        self.set_state(s.get("t", t or time()), s.get("e", 0), s.get("i", 0))
        s.setdefault("setpoint", None)

    def setpoint(self, setpoint):
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

    def move_to(self, i, o, t=None):
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

    def __call__(self, i: float, t=None) -> float:
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

    def integrate(self, i, t=None) -> tuple[float, float, float]:
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
