#
# Created on Wed Jun 22 20:06:38 2022
#
# @author: eadali
#
# extended for MoaT by Matthias Urlichs
#

from __future__ import annotations

from math import exp

from moat.util import NotGiven, attrdict
from moat.lib.micro import ticks_diff

from typing import TYPE_CHECKING

__all__ = []

if TYPE_CHECKING:
    from types import EllipsisType

    from collections.abc import Sequence

try:
    # MicroPython. Use milliseconds. Type resolved below.
    from time import ticks_ms as time  # type:ignore[unresolved-import]

    PID_TC = 1000
    MAX_VAL = 2**31 - 1

except ImportError:
    # Standard Python
    from time import monotonic as time

    PID_TC = 1
    MAX_VAL = float("inf")


class PID:
    """
    An advanced PID controller with first-order filter on derivative term.
    """

    t: float | None = None
    e: float | None = None
    _err: float | None = None
    i: float = 0

    Kp: float
    Ki: float | None
    Kd: float | None
    Tf: float | None

    lower: float = -MAX_VAL
    upper: float = MAX_VAL

    fct: float = 1
    off: float = 0

    def __init__(
        self,
        Kp: float | None = None,
        Ki: float | None = None,
        Kd: float | None = None,
        Tf: float | None = None,
        t: float | None = None,
    ):
        """
        Args:
            Kp: proportional term
            Ki: integral term.
            Kd: derivative term.
            Tf: Time constant for first-order filter on the derivative
            t: current / initial time

        Attributes:
            t: current time
            e: current differential error
            i: current integral sum

            lower: Lower limit of the output
            upper: Upper limit of the output
        """
        self.set_gains(Kp, Ki, Kd, Tf)
        self.set_output_limits()
        self.reset(t)

    def reset(self, t: float | None = None, clear: bool = False) -> None:
        """
        Reset the controller.

        Args:
            t:
                current time (if known)
            clear:
                if set, clear internal state so that ``self(0) == 0``
        """
        self.set_state(t, 0 if clear else None, 0 if clear else None)
        if t is None:
            self.t = None

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
        """
        Sum the input values, apply fct+off, and limit the result to the
        interval between `min`…`max`.

        ``pid(signal)`` ≍ ``pid.sum(*self.integrate(signal))``
        """
        return self.off + self.fct * min(max(sum(args), self.lower), self.upper)

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

    def set_offset(self, fct: float | None = None, off: float | None = None) -> None:
        """Set output value factor and offset.

        Args:
            fct: Factor (default 1.0)
            off: Offset (default 0.0)

        Factor and offset are applied by :meth:`sum`.
        """
        if fct is not None:
            self.fct = fct
        if off is not None:
            self.off = off

    def get_offset(self) -> tuple[float, float]:
        """Get output value factor and offset."""
        return self.fct, self.off

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
        old_Kp = getattr(self, "Kp", 0.0)
        old_Kd = getattr(self, "Kd", None)
        old_Tf = getattr(self, "Tf", None)

        new_Kp = Kp or 0
        new_Ki = Ki / PID_TC if Ki else None
        new_Kd = Kd * PID_TC if Kd else None
        new_Tf = Tf * PID_TC if Tf else None

        err = self._err
        if err is None:
            err = self.e

        if err is not None:
            # keep p+i continuous across gain changes
            self.i += (old_Kp - new_Kp) * err

            if old_Kd and old_Tf and self.e is not None:
                if new_Kd and new_Tf:
                    # Adjust derivative filter residual for a bumpless D/Tf change.
                    tdf0 = old_Tf / old_Kd
                    tdf1 = new_Tf / new_Kd
                    self.e = err - (tdf1 / tdf0) * (err - self.e)
                else:
                    self.e = err
            elif new_Kd and new_Tf:
                self.e = err

        self.Kp = new_Kp
        self.Ki = new_Ki
        self.Kd = new_Kd
        self.Tf = new_Tf

    def set_output_limits(self, lower: float | None = None, upper: float | None = None):
        """Set PID controller output limits, for anti-windup.

        Args:
            lower: Lower limit for anti-windup,
            upper: Upper limit for anti-windup.

        """
        if lower is not None:
            self.lower = lower
        if upper is not None:
            self.upper = upper

    def get_output_limits(self) -> tuple[float, float]:
        """Get PID controller output limits for anti-windup.

        Returns: Output limits (lower, upper).

        """
        return self.lower, self.upper

    def set_state(
        self,
        t: float | None | EllipsisType = None,
        e: float | None = None,
        i: float | None = None,
    ) -> None:
        """Set PID controller states.

        Args:
            t:
                Current time. If NotGiven, clears.
            e:
                Current error.
            i:
                Current integral.

        """
        if t is NotGiven:
            self.t = None
        elif t is not None:
            self.t = t
        if e is not None:
            self.e = e
            self._err = e
        if i is not None:
            self.i = i

    def get_state(self) -> tuple[float | None, float | None, float]:
        """Get PID controller states.

        Returns:
            State of the PID controller (t, e, i)

        """
        return self.t, self.e, self.i

    def integrate(self, e: float, t: float | None = None) -> tuple[float, float, float]:
        """Calculates PID controller output.

        Args:
            e: Error signal.
            t: Current time.

        Returns:
            ``p,i,d``: Control signal (in parts), *not* limited.

        This method performs anti-windup protection on the controller's integral term.
        """
        e1 = e
        t0, e0, i0 = self.get_state()
        if t is None:
            t = time()

        if t0 is None:
            t0 = t
        if e0 is None:
            e0 = e

        # Calculate time step
        dt = ticks_diff(t, t0)
        if dt < 0:
            self.t = t
            raise ValueError(f"Time went backwards: {t} {t0} {dt}")

        # Calculate proportional term
        p = self.Kp * e
        # Calculate integral term
        if self.Ki:
            i = i0 + dt * self.Ki * e
            # anti-windup
            i = min(max(i, min(self.lower - p, 0)), max(self.upper - p, 0))
        else:
            i = i0

        # Calculate possibly-delayed derivative term
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
        self._err = e1

        return p, i, d


class CPID(PID):
    """
    A PID that's configured with a config dictionary.

    This class accepts the desired and actual system state as input, *not* the error.
    ::

        flow:
            p: 0.1
            i: 0.01
            d: 0.0
            tf: 0.0  # both d ant tf must be set

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
        Args:
            cfg: our configuration. See above.
            state: the state storage. Typically an :py:class:`moat.util.attrdict`.
        """
        super().__init__(cfg.get("p", 0), cfg.get("i", 0), cfg.get("d", 0), cfg.get("tf", 0))
        self.cfg = cfg
        self.cfg_updated()

        if state is None:
            state = attrdict()
        self.state = state
        self.set_state(state.get("t", t or time()), state.get("e", 0), state.get("i", 0))
        state.setdefault("setpoint", None)

    def cfg_updated(self):
        "Config has been updated"
        cg = self.cfg.get
        super().set_gains(cg("p", None), cg("i", None), cg("d", None), cg("tf", None))
        self.set_output_limits(self.cfg.get("min", None), self.cfg.get("max", None))
        self.set_offset(self.cfg.get("fct", None), self.cfg.get("off", None))

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

        # the default is a no-op adjustment so the factor is zero not one
        if osp is not None:
            i -= osp * self.cfg.get("factor", 0) + self.cfg.get("offset", 0)
        self.state.setpoint = nsp = setpoint
        i += nsp * self.cfg.get("factor", 0) + self.cfg.get("offset", 0)

        self.i = i

    def move_to(self, i: float, o: float, t=None):
        """
        Tell the controller that this input shall result in that output,
        by mangling its internal state as required.

        This method only works with a valid setpoint. It can be used to
        bumpless-ly hand control from one PID to another.

        Args:
            i: current process state
            o: desired controller state
        """
        if t is None:
            t = time()
        self.t = t
        if self.state.setpoint is not None:
            i -= self.state.setpoint
            self.i = o + i * self.Kp
            self.e = i

    def __call__(self, i: float, t: float | None = None) -> float:  # type:ignore[invalid-method-override]
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
        res = super().__call__(e=self.state.setpoint - i, t=t)
        self._update_state()
        return res

    def integrate(self, i: float, t=None) -> tuple[float, float, float]:  # type:ignore[call-non-callable]
        """
        Run a PID step.

        Args:
            i: the current output.
            t: current time, or `None` for monotonicity.
        Returns:
            the p,i,d control variables.
            Call :meth:`PID.sum` to get the new input.
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
