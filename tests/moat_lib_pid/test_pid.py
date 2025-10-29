"""
Created on Mon Jun 20 19:45:34 2022

@author: eadali
"""

from __future__ import annotations

import pytest
from math import cos, pi, sin

from numpy import allclose, arange, array, diff, insert, zeros_like

from moat.lib.pid import PID, PID_TC

from typing import cast

if True:
    # Hack to test non-second time intervals
    from moat.lib.pid import pid as _pid
    from moat.util.compat import ticks_ms

    _pid.PID_TC = PID_TC = 1000
    _pid.time = ticks_ms


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


def test_init_set_gains():  # noqa:D103
    # Set gains
    Kp, Ki, Kd, Tf = 1.0, 2.0, 3.0, 4.0
    # Create PID controller and get gains
    pid = PID(Kp=Kp, Ki=Ki, Kd=Kd, Tf=Tf)
    _Kp, _Ki, _Kd, _Tf = pid.get_gains()
    # Check
    assert almost_equal(Kp, _Kp)
    assert almost_equal(Ki, _Ki)
    assert almost_equal(Kd, _Kd)
    assert almost_equal(Tf, _Tf)


def test_set_gains():  # noqa:D103
    # Set gains
    Kp, Ki, Kd, Tf = 1.0, 2.0, 3.0, 4.0
    # Create PID controller and set gains
    pid = PID(Kp=0.0, Ki=0.0, Kd=0.0, Tf=0.05)
    pid.set_gains(Kp=Kp, Ki=Ki, Kd=Kd, Tf=Tf)
    # Get PID gains
    _Kp, _Ki, _Kd, _Tf = pid.get_gains()
    # Check
    assert almost_equal(Kp, _Kp)
    assert almost_equal(Ki, _Ki)
    assert almost_equal(Kd, _Kd)
    assert almost_equal(Tf, _Tf)


def test_set_output_limits():  # noqa:D103
    # Set output limits
    lower, upper = -4.0, 4.0
    # Create PID controller and set output limits
    pid = PID(Kp=1.0, Ki=2.0, Kd=3.0, Tf=4.0)
    # Get PID output limits
    pid.set_output_limits(lower=lower, upper=upper)
    _lower, _upper = pid.get_output_limits()
    # Check
    assert almost_equal(lower, _lower)
    assert almost_equal(upper, _upper)


def test_set_state():  # noqa:D103
    # Set initial values
    t0, e0, i0 = 5.0, 6.0, 7.0
    # Create PID controller and set initial values
    pid = PID(Kp=1.0, Ki=2.0, Kd=3.0, Tf=4.0)
    pid.set_state(t=t0, e=e0, i=i0)
    # Get PID initial values
    _t, _e, _i = pid.get_state()
    # Check
    assert almost_equal(t0, _t)
    assert almost_equal(e0, _e)
    assert almost_equal(i0, _i)


def test_integrate_only_p():  # noqa:D103
    # Set Kp gain
    Kp = 2.0
    # Create PID controller
    pid = PID(Kp=Kp, Ki=0.0, Kd=0.0, Tf=0.05, t=0)
    # Create simulation time array, error and output array
    time = arange(0, 10, 0.1)
    error, output = zeros_like(time), zeros_like(time)
    for idx, t in enumerate(time):
        t = cast(float, t)
        # Calculate error signal
        e = sin(0.5 * pi * t)
        # Get PID output signal
        u = pid(e, t=t * PID_TC)
        # Record error and output signal
        error[idx] = e
        output[idx] = u
    # Check
    assert allclose(Kp * error, output, rtol=0.0, atol=1e-08)


def test_integrate_only_i():  # noqa:D103
    # Set Ki gain
    Ki = 2.0
    # Set simulation time step
    dt = 0.1
    # Create PID controller
    pid = PID(Kp=0.0, Ki=Ki, Kd=0.0, Tf=0.05, t=0)
    # Create simulation time array, error and output array
    time = arange(0, 10, dt)
    error, output = zeros_like(time), zeros_like(time)
    for idx, t in enumerate(time):
        t = cast(float, t)
        # Calculate error signal
        e = sin(0.5 * pi * t)
        # Get PID output
        u = pid(e, t=t * PID_TC)
        # Record error and output signal
        error[idx] = e
        output[idx] = u
    # Check
    expected = Ki * dt * error.cumsum()
    assert allclose(expected, output, rtol=0.0, atol=1e-08)


def test_integrate_only_d():  # noqa:D103
    # Set Kd and Tf gains
    Kd, Tf = 3.2, 0.05
    # Set simulation time step
    dt = 0.1
    # Create PID controller
    pid = PID(Kp=0.0, Ki=0.0, Kd=Kd, Tf=Tf, t=0)
    # Create simulation time array, error and output array
    time = arange(0, 10, dt)
    error, output = zeros_like(time), zeros_like(time)
    for idx, t in enumerate(time):
        t = cast(float, t)
        # Calculate error signal
        e = cos(0.5 * pi * t)
        # Get PID output
        u = pid(e, t=t * PID_TC)
        # Record error and output signal
        error[idx] = e
        output[idx] = u
    # Check
    expected = (1 / dt) * insert(diff(error), 0, 0)
    assert allclose(expected, output, rtol=0.0, atol=0.1)


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
def test_integrate_full(Kp, Ki, Kd, Tf, ok):  # noqa:D103
    # Set simulation time step
    dt = 0.1
    # Create PID controller
    pid = PID(Kp=Kp, Ki=Ki, Kd=Kd, Tf=Tf, t=0)
    # Create simulation time array, error and output array
    time = arange(0, 10, dt)
    error, output = zeros_like(time), zeros_like(time)
    for idx, t in enumerate(time):
        t = cast(float, t)
        # Calculate error signal
        e = cos(0.5 * pi * t)
        # Get PID output
        u = pid(e, t=t * PID_TC)
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
    expected = array(eval(exp.strip()))
    assert ok == allclose(expected, output, rtol=0.0, atol=0.1)
    if ok:
        assert pid.get_gains() == (0, 2.0, 3.2, 0.5)


def test_integrate_one():  # noqa:D103
    # Set gains
    Kp, Ki, Kd, Tf = 2.0, 2.0, 2.0, 0.05
    # Set simulation time step
    dt = 0.1
    # Create PID controller
    pid = PID(Kp=Kp, Ki=Ki, Kd=Kd, Tf=Tf * PID_TC, t=0)
    # Create simulation time array, error and output array
    time = arange(0, 10, dt)
    error, output = zeros_like(time), zeros_like(time)
    for idx, t in enumerate(time):
        t = cast(float, t)
        # Calculate error signal
        e = 1
        # Get PID output
        u = pid(e, t=t * PID_TC)
        # Record error and output signal
        error[idx] = e
        output[idx] = u
    # Check

    expected = Kp * error + Ki * dt * (error.cumsum() - error[0])
    assert allclose(expected, output, rtol=0.0, atol=1e-08)


def test_integrate_anti_windup():  # noqa:D103
    # Set Ki gain
    Ki = 2.0
    # Set output limits
    lower, upper = -4.0, 4.0
    # Set simulation time step
    sim_time, dt = 10, 0.1
    # Create PID controller and set output limits
    pid = PID(Kp=0.0, Ki=Ki, Kd=0.0, Tf=0.05 * PID_TC, t=0)
    pid.set_output_limits(lower=lower, upper=upper)
    # Create simulation time array, error and output array
    time = arange(0, sim_time, dt)
    error, output = zeros_like(time), zeros_like(time)
    # Create PID internal integral array
    integral = zeros_like(time)
    for idx, t in enumerate(time):
        t = cast(float, t)
        # Calculate error signal
        if t < (sim_time / 2.0):
            e = +1.0
        else:
            e = -1.0
        # Get PID output
        u = pid(e, t=t * PID_TC)
        i = pid.get_state()[2]
        # Record error and output signal
        integral[idx] = i
        error[idx] = e
        output[idx] = u
    # Check
    assert almost_equal(lower, output.min())
    assert almost_equal(upper, output.max())
    assert almost_equal(lower, integral.min())
    assert almost_equal(upper, integral.max())
