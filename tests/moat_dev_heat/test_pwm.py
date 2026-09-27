"""
Tests for the software-PWM daemon and the Solvis Modbus monitor (fake GPIO,
fake process, real MoaT-Link test server).
"""

from __future__ import annotations

import anyio
import pytest
from contextlib import asynccontextmanager

from moat.dev.heat.modbus_mon import ModbusMonCfg, run_modbus_mon
from moat.dev.heat.pwm import OutputCfg, Override, duty, run_output
from moat.lib.path import P

from typing import Any

VALUE = P("test.pwm.value")
FLAG = P("test.pwm.flag")
OVR = P("test.pwm.ovr")
PIN = 4


@pytest.mark.parametrize(
    ("value", "flag", "ovr", "want"),
    [
        (0.5, None, None, 0.5),
        (None, None, None, 0.0),
        ("x", None, None, 0.0),
        (True, None, None, 0.0),
        (0.005, None, None, 0.0),
        (0.995, None, None, 1.0),
        (1.5, None, None, 1.0),
        (-1, None, None, 0.0),
        (0.2, False, 0.8, 0.2),
        (0.2, True, 0.8, 0.8),
        (0.2, True, None, 0.0),
    ],
)
def test_duty(value: Any, flag: Any, ovr: Any, want: float) -> None:
    "value, override precedence and the 0/1 edges"
    assert duty(value, flag, ovr) == want


class FakeGPIO:
    "records pin levels with their time"

    OUT = 1

    def __init__(self) -> None:
        self.log: list[tuple[float, int, bool]] = []
        self.modes: dict[int, int] = {}

    def setup(self, pin: int, mode: int) -> None:
        "configure a pin"
        self.modes[pin] = mode

    def output(self, pin: int, level: bool) -> None:
        "set a pin"
        self.log.append((anyio.current_time(), pin, bool(level)))

    def on_fraction(self, t0: float, t1: float, active: bool = True) -> float:
        "fraction of [t0, t1] during which the pin was at the active level"
        on = 0.0
        level = None
        last = t0
        for t, _, lv in self.log:
            if t < t0:
                level = lv
                continue
            if t > t1:
                break
            if level == active:
                on += t - last
            level, last = lv, t
        if level == active:
            on += t1 - last
        return on / (t1 - t0)


CFG = OutputCfg(pin=PIN, path=VALUE, freq=50, override=Override(flag=FLAG, val=OVR))


async def _measure(link, cfg: OutputCfg, **values: Any) -> tuple[FakeGPIO, float]:
    "set the values, run the output for a while, return the GPIO and the on-fraction"
    for k, v in values.items():
        await link.d_set({"value": VALUE, "flag": FLAG, "ovr": OVR}[k], v, retain=True)
    gpio = FakeGPIO()
    async with anyio.create_task_group() as tg:
        await tg.start(run_output, link, "test", cfg, gpio)
        await anyio.sleep(0.2)  # settle
        t0 = anyio.current_time()
        await anyio.sleep(0.6)
        t1 = anyio.current_time()
        tg.cancel_scope.cancel()
    return gpio, gpio.on_fraction(t0, t1, active=not cfg.inverted)


@pytest.mark.anyio
async def test_pwm_levels(link):
    "0, 1 and a duty cycle in between; the pin is inactive afterwards"
    g, f = await _measure(link, CFG, value=0.0)
    assert f == 0
    assert g.modes[PIN] == FakeGPIO.OUT
    g, f = await _measure(link, CFG, value=1.0)
    assert f == 1
    g, f = await _measure(link, CFG, value=0.5)
    assert 0.3 < f < 0.7
    assert g.log[-1][2] is False


@pytest.mark.anyio
async def test_pwm_inverted(link):
    "an inverted output is active low, and ends high"
    cfg = CFG.model_copy(update={"inverted": True})
    g, f = await _measure(link, cfg, value=1.0)
    assert f == 1
    assert g.log[-1][2] is True
    assert not any(lv for _, _, lv in g.log[1:-1])


@pytest.mark.anyio
async def test_pwm_override(link):
    "the override value wins while the flag is set"
    _, f = await _measure(link, CFG, value=0.0, flag=True, ovr=1.0)
    assert f == 1
    _, f = await _measure(link, CFG, value=0.0, flag=False, ovr=1.0)
    assert f == 0


# Modbus monitor

ERR = P("test.solvis.errors")


class FakeProcs:
    "stands in for anyio.open_process; counts starts and kills"

    def __init__(self) -> None:
        self.starts = 0
        self.kills = 0
        self.started = anyio.Event()

    async def __call__(self, cmd: list[str]) -> Any:
        "start a fake poller"
        assert cmd[:4] == ["moat", "modbus", "dev", "poll"]
        me = self

        class Proc:
            def kill(self) -> None:
                "count the kill"
                me.kills += 1

        @asynccontextmanager
        async def ctx():
            me.starts += 1
            me.started.set()
            me.started = anyio.Event()
            yield Proc()

        return ctx()


@pytest.mark.anyio
@pytest.mark.parametrize(("code", "restart"), [(26, True), (12, False)])
async def test_modbus_mon(link, code: int, restart: bool) -> None:
    "the poller is restarted on error 26, and only then"
    cfg = ModbusMonCfg(err=ERR, settle=0.1, pause=0.05, restart_timeout=1)
    procs = FakeProcs()
    async with anyio.create_task_group() as tg:
        await tg.start(run_modbus_mon, link, cfg, procs)
        assert procs.starts == 1
        await anyio.sleep(0.3)
        await link.d_set(ERR / 1 / "code", code, retain=True)
        await link.i_sync()
        await link.d_set(ERR, True, retain=True)
        with anyio.move_on_after(1):
            await procs.started.wait()
        tg.cancel_scope.cancel()
    assert procs.starts == (2 if restart else 1)
    assert procs.kills == procs.starts


def test_modbus_mon_needs_err():
    "without the error path there's nothing to monitor"
    with pytest.raises(ValueError, match="err"):
        anyio.run(run_modbus_mon, None, ModbusMonCfg())
