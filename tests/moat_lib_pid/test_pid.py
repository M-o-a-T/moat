#!/usr/bin/env python3
"""
Created on Mon Jun 20 19:45:34 2022

@author: eadali
"""

from __future__ import annotations

from numpy import arange, zeros_like, allclose, diff, insert
from math import sin, cos, pi
from moat.lib.pid import PID
import unittest


class TestStringMethods(unittest.TestCase):
    def test_init_set_gains(self):
        # Set gains
        Kp, Ki, Kd, Tf = 1.0, 2.0, 3.0, 4.0
        # Create PID controller and get gains
        pid = PID(Kp=Kp, Ki=Ki, Kd=Kd, Tf=Tf)
        _Kp, _Ki, _Kd, _Tf = pid.get_gains()
        # Check
        self.assertAlmostEqual(Kp, _Kp)
        self.assertAlmostEqual(Ki, _Ki)
        self.assertAlmostEqual(Kd, _Kd)
        self.assertAlmostEqual(Tf, _Tf)

    def test_set_gains(self):
        # Set gains
        Kp, Ki, Kd, Tf = 1.0, 2.0, 3.0, 4.0
        # Create PID controller and set gains
        pid = PID(Kp=0.0, Ki=0.0, Kd=0.0, Tf=0.05)
        pid.set_gains(Kp=Kp, Ki=Ki, Kd=Kd, Tf=Tf)
        # Get PID gains
        _Kp, _Ki, _Kd, _Tf = pid.get_gains()
        # Check
        self.assertAlmostEqual(Kp, _Kp)
        self.assertAlmostEqual(Ki, _Ki)
        self.assertAlmostEqual(Kd, _Kd)
        self.assertAlmostEqual(Tf, _Tf)

    def test_set_output_limits(self):
        # Set output limits
        lower, upper = -4.0, 4.0
        # Create PID controller and set output limits
        pid = PID(Kp=1.0, Ki=2.0, Kd=3.0, Tf=4.0)
        # Get PID output limits
        pid.set_output_limits(lower=lower, upper=upper)
        _lower, _upper = pid.get_output_limits()
        # Check
        self.assertAlmostEqual(lower, _lower)
        self.assertAlmostEqual(upper, _upper)

    def test_set_initial_value(self):
        # Set initial values
        t0, e0, i0 = 5.0, 6.0, 7.0
        # Create PID controller and set initial values
        pid = PID(Kp=1.0, Ki=2.0, Kd=3.0, Tf=4.0)
        pid.set_initial_value(t0=t0, e0=e0, i0=i0)
        # Get PID initial values
        _t, _e, _i = pid.get_initial_value()
        # Check
        self.assertAlmostEqual(t0, _t)
        self.assertAlmostEqual(e0, _e)
        self.assertAlmostEqual(i0, _i)

    def test_integrate_only_p(self):
        # Set Kp gain
        Kp = 2.0
        # Create PID controller
        pid = PID(Kp=Kp, Ki=0.0, Kd=0.0, Tf=0.05)
        # Create simulation time array, error and output array
        time = arange(0, 10, 0.1)
        error, output = zeros_like(time), zeros_like(time)
        for idx, t in enumerate(time):
            # Calculate error signal
            e = sin(0.5 * pi * t)
            # Get PID output signal
            u = pid.integrate(t, e)
            # Record error and output signal
            error[idx] = e
            output[idx] = u
        # Check
        assert allclose(Kp * error, output, rtol=0.0, atol=1e-08)

    def test_integrate_only_i(self):
        # Set Ki gain
        Ki = 2.0
        # Set simulation time step
        dt = 0.1
        # Create PID controller
        pid = PID(Kp=0.0, Ki=Ki, Kd=0.0, Tf=0.05)
        # Create simulation time array, error and output array
        time = arange(0, 10, dt)
        error, output = zeros_like(time), zeros_like(time)
        for idx, t in enumerate(time):
            # Calculate error signal
            e = sin(0.5 * pi * t)
            # Get PID output
            u = pid.integrate(t, e)
            # Record error and output signal
            error[idx] = e
            output[idx] = u
        # Check
        expected = Ki * dt * error.cumsum()
        assert allclose(expected, output, rtol=0.0, atol=1e-08)

    def test_integrate_only_d(self):
        # Set Kd and Tf gains
        Kd, Tf = 3.2, 0.05
        # Set simulation time step
        dt = 0.1
        # Create PID controller
        pid = PID(Kp=0.0, Ki=0.0, Kd=Kd, Tf=Tf)
        # Create simulation time array, error and output array
        time = arange(0, 10, dt)
        error, output = zeros_like(time), zeros_like(time)
        for idx, t in enumerate(time):
            # Calculate error signal
            e = cos(0.5 * pi * t)
            # Get PID output
            u = pid.integrate(t, e)
            # Record error and output signal
            error[idx] = e
            output[idx] = u
        # Check
        expected = (1 / dt) * insert(diff(error), 0, 0)
        assert allclose(expected, output, rtol=0.0, atol=0.1)

    def test_integrate_one(self):
        # Set gains
        Kp, Ki, Kd, Tf = 2.0, 2.0, 2.0, 0.05
        # Set simulation time step
        dt = 0.1
        # Create PID controller
        pid = PID(Kp=Kp, Ki=Ki, Kd=Kd, Tf=Tf)
        # Create simulation time array, error and output array
        time = arange(0, 10, dt)
        error, output = zeros_like(time), zeros_like(time)
        for idx, t in enumerate(time):
            # Calculate error signal
            e = 1
            # Get PID output
            u = pid.integrate(t, e)
            # Record error and output signal
            error[idx] = e
            output[idx] = u
        # Check

        expected = Kp * error + Ki * dt * (error.cumsum() - error[0])
        assert allclose(expected, output, rtol=0.0, atol=1e-08)

    def test_integrate_anti_windup(self):
        # Set Ki gain
        Ki = 2.0
        # Set output limits
        lower, upper = -4.0, 4.0
        # Set simulation time step
        sim_time, dt = 10, 0.1
        # Create PID controller and set output limits
        pid = PID(Kp=0.0, Ki=Ki, Kd=0.0, Tf=0.05)
        pid.set_output_limits(lower=lower, upper=upper)
        # Create simulation time array, error and output array
        time = arange(0, sim_time, dt)
        error, output = zeros_like(time), zeros_like(time)
        # Create PID internal integral array
        integral = zeros_like(time)
        for idx, t in enumerate(time):
            # Calculate error signal
            if t < (sim_time / 2.0):
                e = +1.0
            else:
                e = -1.0
            # Get PID output
            u = pid.integrate(t, e)
            i = pid.get_initial_value()[2]
            # Record error and output signal
            integral[idx] = i
            error[idx] = e
            output[idx] = u
        # Check
        self.assertAlmostEqual(lower, output.min())
        self.assertAlmostEqual(upper, output.max())
        self.assertAlmostEqual(lower, integral.min())
        self.assertAlmostEqual(upper, integral.max())


if __name__ == "__main__":
    unittest.main()
