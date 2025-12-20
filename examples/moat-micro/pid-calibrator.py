#!/usr/bin/python3
"""
This program runs a PID link calibration.

To use it you need a moat.micro configuration that contains a sensor
("value": whatever you want to control) and an output ("control":
whatever controls the process).

This code sets the output, waits until the value exceeds your threshold,
clears the output, then waits until the value is below the threshold.
It repeats this a number of times, then prints the results.

The data can then be used as initial tuning values for a PID algorithm.
Specifically, this code

"""

from __future__ import annotations

import anyio
import math
import sys
import time

import asyncclick as click

from moat.util import P
from moat.link.client import Link
from moat.main import main_, run
from moat.micro.cmd.tree.dir import Dispatch
from moat.util.times import humandelta


async def main(ctx: click.Context):
    "PID calibrator main code"
    obj = ctx.obj
    cfg = obj.cfg
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg))


@main_.command
@click.option("-S", "--section", type=P, help="Config section to use", default=P("micro.connect"))
@click.option("-t", "--threshold", type=float, required=True, help="Threshold for on/off")
@click.option("-c", "--control", type=P, required=True, help="Control output")
@click.option("-v", "--value", type=P, required=True, help="Value input")
@click.option("-m", "--min", "c_min", type=float, help="Min/off control", default=0)
@click.option("-M", "--max", "c_max", type=float, help="Max/on control", default=1)
@click.option("-E", "--end", type=float, help="Control after test completes", default=None)
@click.option("-n", "--tests", type=int, help="Number of test half-cycles", default=6)
@click.option("-b", "--blind", type=int, help="Number of initial test half-cycles", default=3)
@click.option("-T", "--hysteresis", type=float, help="Hysteresis around threshold", default=0.1)
@click.option("-i", "--invert", is_flag=True, help="Increasing control lowers input")
@click.option("-d", "--delay", type=float, help="Delay between measurements", default=10)
@click.option("-L", "--limit", type=float, help="Total runtime limit (safety), hours", default=3)
@click.pass_context
async def cal(
    ctx,
    threshold,
    control,
    value,
    c_min,
    c_max,
    end,
    tests,
    hysteresis,
    invert,
    section,
    limit,
    blind,
    delay,
):
    """
    Calibrate a PID controller.

    We set the control to "max", wait until the value exceeds the
    threshold, set the control to "min", wait until the value is below
    the threshold, repeat.

    The result is used to calculate initial PID parameters
    (via the Ziegler-Nichols method:
    https://en.wikipedia.org/wiki/Ziegler%E2%80%93Nichols_method).
    """
    obj = ctx.obj
    cfg = obj.cfg.get_(section)

    if end is None:
        end = c_min

    # could use "async with" here but this code is indented enough
    mic = await ctx.with_async_resource(Dispatch(cfg, run=True))
    in_ = mic.sub_at(value)
    out_ = mic.sub_at(control)
    dir_ = True
    t_last = time.monotonic()
    v_min = []
    v_max = []
    t_min = []
    t_max = []

    async def go(ignore: bool = False):
        nonlocal dir_, t_last
        await out_(c_max if dir_ else c_min)
        dd = dir_ != invert
        a = "🡳🡱↓↑"[2 * ignore + dd]
        d = 0

        while True:
            val = await in_()
            t = time.monotonic()
            if obj.debug:
                print(
                    "",
                    f"{a} {val:6.2f}  {humandelta(t - t_last)}",
                    end="          \r",
                    file=sys.stderr,
                )
                sys.stderr.flush()

            d = max(d, abs(threshold - val))

            if (val > threshold + hysteresis) if dd else (val < threshold - hysteresis):
                tt = t - t_last
                if not ignore:
                    (v_max if dd else v_min).append(d)
                    (t_max if dd else t_min).append(tt)
                print(f"{a} {d:4.2f}  {humandelta(tt)}           ")

                t_last = t
                dir_ = not dir_
                return

            await anyio.sleep(delay)

    try:
        with anyio.fail_after(limit * 3600):
            # initial ramp-up is not measured
            for _ in range(blind + 1):
                await go(True)
            for _ in range(tests):
                await go()

        v_avg_min = sum(v_min) / len(v_min)
        v_avg_max = sum(v_max) / len(v_max)
        v_avg = v_avg_min + v_avg_max

        t_avg_min = sum(t_min) / len(t_min)
        t_avg_max = sum(t_max) / len(t_max)
        t_avg = t_avg_min + t_avg_max

        ku = 4 * v_avg / math.pi / (c_max - c_min)
        tu = t_avg

        # Basic
        # kpc,tic,tdc = .6,.5,.125
        # less overshoot
        kpc, tic, tdc = 0.33, 0.5, 0.33
        # no overshoot
        # kpc,tic,tdc = .2,.5,.33

        kp = kpc * ku
        ki = kp / (tic * tu)
        kd = tdc * kp * tu

        print(f"Delta min: {v_avg_min:5.2f}", ",".join(f"{v:5.2f}" for v in v_min))
        print(f"Delta max: {v_avg_max:5.2f}", ",".join(f"{v:5.2f}" for v in v_max))
        print(f"Times min: {t_avg_min:5.2f}", ",".join(f"{t:5.2f}" for t in t_min))
        print(f"Times max: {t_avg_max:5.2f}", ",".join(f"{t:5.2f}" for t in t_max))

        print("Calculated p,i,d:")
        print(kp, ki, kd)

    finally:
        with anyio.move_on_after(2, shield=True):
            await out_(end)


run(main, doc="PID calibrator.")
