"""
Software PWM for GPIO outputs, driven from MoaT-Link (HEAT.md §3.10).

Port of the legacy ``pwm`` command. Each output watches a value path
(0…1, e.g. the flow unit's ``heat.s.pump.pid``) and, optionally, an
override flag and value (e.g. Home Assistant helpers for testing), and
drives a GPIO pin at a fixed frequency. ``RPi.GPIO`` is imported only
when the outputs actually run; tests pass their own GPIO object.
"""

from __future__ import annotations

import anyio
import logging

import asyncclick as click

from moat.lib.config.base import BaseModel
from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)
from moat.util.times import t_iter

from .config import UnitCfg
from .link import Reader

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import TaskStatus

    from moat.link.client import LinkSender

__all__ = ["OutputCfg", "Override", "PwmCfg", "cli", "duty", "run_output", "run_pwm"]

_logger = logging.getLogger(__name__)


class Override(BaseModel):
    """Operator override of one output."""

    flag: Path
    """While this is true …"""
    val: Path
    """… this value is used instead of the output's own."""


class OutputCfg(BaseModel):
    """One software-PWM output."""

    pin: int
    """BCM pin number."""
    path: Path
    """The value (0…1) to output."""
    freq: float = 200
    """PWM frequency, Hz."""
    inverted: bool = False
    """The pin is active low."""
    override: Override | None = None


class PwmCfg(UnitCfg):
    """Configuration of the PWM daemon: its outputs, by name."""

    outputs: dict[str, OutputCfg] = {
        "flow": OutputCfg(
            pin=4,
            path=P("heat.s.pump.pid"),
            override=Override(
                flag=P("home.ass.state.input_boolean.test_override_on.state"),
                val=P("home.ass.state.input_number.test_override_pct.state"),
            ),
        )
    }


def duty(value: Any, flag: Any = None, override: Any = None) -> float:
    """
    The duty cycle to output.

    The override value wins while the flag is true. Anything that isn't a
    number counts as 0; the result is limited to 0…1. Values below 1 %
    are off, above 99 % on, as in the legacy daemon.
    """
    v = override if flag else value
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0.0
    if v < 0.01:
        return 0.0
    if v > 0.99:
        return 1.0
    return float(v)


async def run_output(
    link: LinkSender,
    name: str,
    cfg: OutputCfg,
    gpio: Any,
    *,
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """
    Drive one output until cancelled; the pin is left inactive.

    Args:
        link: The MoaT-Link client.
        name: The output's name, for logging.
        cfg: The output's configuration.
        gpio: The ``RPi.GPIO`` module (or a stand-in).
    """
    value = Reader[float](link, cfg.path)
    flag = Reader[bool](link, cfg.override.flag) if cfg.override else None
    ovr = Reader[float](link, cfg.override.val) if cfg.override else None
    on, off = not cfg.inverted, cfg.inverted

    gpio.setup(cfg.pin, gpio.OUT)
    gpio.output(cfg.pin, off)
    last = None
    try:
        async with anyio.create_task_group() as tg:
            for r in (value, flag, ovr):
                if r is not None:
                    await tg.start(r.run)
            task_status.started()

            period = 1 / cfg.freq
            async for _ in t_iter(period):
                d = duty(
                    value.value,
                    flag.value if flag else None,
                    ovr.value if ovr else None,
                )
                if d != last:
                    _logger.info("PWM %s: %.3f", name, d)
                    last = d
                if d <= 0:
                    gpio.output(cfg.pin, off)
                    continue
                gpio.output(cfg.pin, on)
                if d >= 1:
                    continue
                await anyio.sleep(d * period)
                gpio.output(cfg.pin, off)
    finally:
        gpio.output(cfg.pin, off)


def _gpio() -> Any:
    import RPi.GPIO as GPIO  # noqa: PLC0415

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    return GPIO


async def run_pwm(
    link: LinkSender,
    cfg: PwmCfg,
    gpio: Any = None,
    *,
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """
    Drive all configured outputs until cancelled.

    Args:
        link: The MoaT-Link client.
        cfg: The daemon's configuration.
        gpio: The GPIO module; default: ``RPi.GPIO``, imported now.
    """
    if gpio is None:
        gpio = _gpio()
    async with anyio.create_task_group() as tg:
        for name, out in cfg.outputs.items():
            await tg.start(run_output, link, name, out, gpio)
        task_status.started()


@click.command(short_help="Software PWM for the heat controller's GPIO outputs.")
@click.pass_obj
async def cli(obj: Any) -> None:
    """
    Drive the configured GPIO outputs (``cfg.app.heat.pwm``) from their
    MoaT-Link values. Needs ``RPi.GPIO``.
    """
    from moat.link.client import Link  # noqa: PLC0415

    from .config import load_config  # noqa: PLC0415

    async with Link(obj.cfg.link) as link:
        cfg = await load_config(link, "pwm", PwmCfg)
        await run_pwm(link, cfg)
