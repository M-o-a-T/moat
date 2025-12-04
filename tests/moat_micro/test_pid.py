"""
Test our ping thing
"""

from __future__ import annotations

import pytest
from math import cos, pi

from numpy import allclose, arange, array, zeros_like

from moat.util import P, yload
from moat.micro._test import mpy_stack

from typing import cast

pytestmark = pytest.mark.anyio

CFG = """
apps:
  r: _test.MpyCmd
  _sys: _sys.Cmd
  p: part.PID
r:
  mplex: true
  cfg:
    apps:
      r: stdio.StdIO
      c: cfg.Cmd
      p: part.PID
      _sys: _sys.Cmd
    r:
      link: &link
        lossy: false
        guarded: false
      log:
        txt: "S"
    p: &p
      t: 10
      p: 1
      i: 0.1
      d: 1
      tf: 10
      max: 5
      min: -5

  link: *link
  log:
    txt: "M"
p: *p

"""


@pytest.mark.parametrize(
    "Kp,Ki,Kd,Tf,ok".split(","),
    [
        (0, 2.0, 3.2, 0.5, True),
        (1, 2.0, 3.2, 0.5, False),
        (0, 3.0, 3.2, 0.5, False),
        (0, 2.0, 2.2, 0.5, False),
        (0, 2.0, 3.2, 0.4, False),
    ],
    ids="OK,P,I,D,Tf".split(","),
)
@pytest.mark.parametrize("here", [True, False])
@pytest.mark.anyio
async def test_integrate(tmp_path, Kp, Ki, Kd, Tf, ok, here):
    "test data foo"
    cfg = yload(CFG, attr=True)
    cfg.p.p = Kp
    cfg.p.i = Ki
    cfg.p.d = Kd
    cfg.p.tf = Tf

    async with (
        mpy_stack(tmp_path, cfg) as d,
        d.sub_at(P("p") if here else P("r.p")) as pid,
    ):
        await integrate_full(pid, ok, here)


def almost_equal(first, second, places=None, delta=None):
    "almost-equal"
    if first == second:
        # shortcut
        return True
    if delta is not None and places is not None:
        raise TypeError("specify delta or places not both")

    diff = abs(first - second)
    if delta is not None:
        if diff <= delta:
            return True

    else:
        if places is None:
            places = 7

        if round(diff, places) == 0:
            return True

    return False


async def integrate_full(pid, ok, here):  # noqa:D103
    # Set simulation time step
    dt = 0.1
    # Create PID controller
    # Create simulation time array, error and output array
    await pid.s(t=0)
    time = arange(0, 10, dt)
    error, output = zeros_like(time), zeros_like(time)
    for idx, t in enumerate(time):
        t = float(cast(float, t))
        # Calculate error signal
        e = cos(0.5 * pi * t)
        # Get PID output
        u = await pid.w(e, t=t if here else int(t * 1000))
        # Record error and output signal
        error[idx] = e
        output[idx] = u

    # Check.
    exp = """[
         0.00,  0.13,  0.14,  0.05, -0.12, -0.36, -0.64, -0.96, -1.28, -1.61,
        -1.93, -2.22, -2.47, -2.67, -2.83, -2.92, -2.96, -2.93, -2.83, -2.67,
        -2.45, -2.17, -1.85, -1.48, -1.08, -0.66, -0.23,  0.20,  0.63,  1.04,
         1.42,  1.77,  2.06,  2.31,  2.49,  2.61,  2.67,  2.65,  2.57,  2.42,
         2.21,  1.94,  1.62,  1.26,  0.87,  0.45,  0.01, -0.41, -0.84, -1.25,
        -1.63, -1.97, -2.27, -2.51, -2.69, -2.81, -2.87, -2.85, -2.77, -2.62,
        -2.41, -2.14, -1.82, -1.46, -1.07, -0.65, -0.22,  0.21,  0.64,  1.05,
         1.43,  1.77,  2.07,  2.31,  2.49,  2.61,  2.67,  2.65,  2.57,  2.42,
         2.21,  1.94,  1.62,  1.26,  0.87,  0.45,  0.02, -0.41, -0.84, -1.25,
        -1.63, -1.97, -2.27, -2.51, -2.69, -2.81, -2.87, -2.85, -2.77, -2.62,
    ]
    """
    expected = -array(eval(exp.strip()))
    assert ok == allclose(expected, output, rtol=0.0, atol=0.1)
