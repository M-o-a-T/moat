"""
Configuration of the heat controller units.

Every unit (and every shared item such as ``service``) has exactly one
configuration object: the package default from ``_cfg.yaml`` merged with
the MoaT-Link item ``cfg.app.heat.<unit>``, the Link item taking
precedence. See HEAT.md §2.4.
"""

from __future__ import annotations

import logging

from moat.util import NotGiven, attrdict, combine_dict
from moat.lib.config import CFG
from moat.lib.config.base import BaseModel
from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)

from collections.abc import Mapping
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from moat.link.client import LinkSender

    from collections.abc import AsyncGenerator
    from typing import Any

__all__ = [
    "CFG_PATH",
    "EmergencyCfg",
    "ServiceCfg",
    "UnitCfg",
    "defaults",
    "load_config",
    "make_config",
    "unit_config",
]

_logger = logging.getLogger(__name__)

M = TypeVar("M", bound="UnitCfg")

#: Location of the per-unit configuration items in MoaT-Link.
CFG_PATH = P("cfg.app.heat")


class UnitCfg(BaseModel):
    """Base class of every unit's configuration model."""


class ServiceCfg(UnitCfg):
    """Service announcement settings shared by all units."""

    host: str = "heat"
    """Host name under which the units announce themselves (``run.host.<host>.heat.<unit>``)."""


class EmergencyCfg(UnitCfg):
    """Tunables of the emergency shutdown procedure (HEAT.md §2.6)."""

    flow_rate: float = 12
    """Flow while draining the heat exchanger, l/min."""
    timeout: float = 120
    """Maximum cool-down wait, seconds."""
    stop_delta: float = 3.0
    """The heat pump has cooled down when ``t_out - t_in`` is below this, K."""
    max_sensor_age: float = 30
    """``t_in``/``t_out`` older than this are ignored, seconds."""
    total_timeout: float = 180
    """Upper bound of the whole procedure, seconds."""
    power_path: Path = P("heat.s.pump.cmd.power")
    mode_path: Path = P("heat.s.pump.cmd.mode")
    mode_off: int = 0
    sensor_in: Path = P("heat.s.pump.temp.in")
    sensor_out: Path = P("heat.s.pump.temp.out")
    flow_request: Path = P("app.heat.flow.request")


def defaults(unit: str) -> attrdict:
    """
    Return the package defaults of a unit.

    Args:
        unit: The unit's name, e.g. ``pump``.
    """
    CFG.with_("moat.dev.heat")
    return CFG.moat.dev.heat.get(unit, attrdict())


def _merge(model: type[M], item: Any, dflt: attrdict) -> M:
    """Validate a Link item combined with the package defaults."""
    if item is NotGiven or item is None:
        data: Mapping = dflt
    elif isinstance(item, Mapping):
        data = combine_dict(item, dflt, cls=attrdict)
    else:
        raise TypeError(f"Config item is not a mapping: {item!r}")
    return model.model_validate(data)


def make_config(unit: str, model: type[M], item: Any = NotGiven) -> M:
    """
    Build a unit's configuration from a (partial) item and the package defaults.

    This is what :func:`load_config` does with the Link item; tests use it
    to configure cores directly.

    Args:
        unit: The unit's name, e.g. ``pump``.
        model: The unit's configuration model.
        item: Overrides, as the Link item would contain them.
    """
    return _merge(model, item, defaults(unit))


async def load_config(link: LinkSender, unit: str, model: type[M]) -> M:
    """
    Return a unit's validated configuration once.

    If the Link item does not validate, the defaults are used.

    Args:
        link: The MoaT-Link client.
        unit: The unit's name, e.g. ``service``.
        model: The unit's configuration model.
    """
    dflt = defaults(unit)
    try:
        item = await link.d_get(CFG_PATH / unit)
    except KeyError:
        item = NotGiven
    try:
        return _merge(model, item, dflt)
    except Exception as exc:
        _logger.warning("Invalid config for %s, ignored: %r", unit, exc)
        return _merge(model, NotGiven, dflt)


async def unit_config(link: LinkSender, unit: str, model: type[M]) -> AsyncGenerator[M]:
    """
    Yield a unit's validated configuration, and again whenever it changes.

    Iterate until cancelled; don't stop early (the watcher runs in a task
    group, which must not be left from a suspended generator).

    The first instance is yielded once the current state of the Link item
    is known; if that item does not validate, the defaults are used. A
    later update that does not validate is logged and skipped, so the
    previous instance stays in effect. Deleting the Link item
    reverts to the package defaults.

    Args:
        link: The MoaT-Link client.
        unit: The unit's name, e.g. ``pump``.
        model: The unit's configuration model.
    """
    dflt = defaults(unit)
    item: Any = NotGiven
    ready = False
    seen = False

    async with link.d_watch(CFG_PATH / unit, meta=True, mark=True) as mon:
        async for msg in mon:
            if msg is None:
                ready = True
            else:
                item = msg[0]
                if not ready:
                    continue
            try:
                cfg = _merge(model, item, dflt)
            except Exception as exc:
                _logger.warning("Invalid config for %s, ignored: %r", unit, exc)
                if seen:
                    continue
                cfg = _merge(model, NotGiven, dflt)
            seen = True
            yield cfg
