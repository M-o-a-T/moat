"""
Scenario files for the plant simulator.

A scenario sets up the plant and then changes it on a schedule::

    seed: 1
    plant:                      # PlantCfg overrides
      buffer: {t_init: [45, 30]}
      weather: {mean: 2, profile: [[0, 3], [21600, -6]]}
    events:
    - {t: 3600, dhw: {duration: 300, lpm: 8}}
    - {t: 7200, error: {path: ":2", code: 123}}
    - {t: 9000, error: {path: ":2", code: 0}}     # 0 clears
    - {t: 10800, stale: t_out}                    # stops updating
    - {t: 12600, fresh: t_out}
    - {t: 14400, stuck: {sensor: tb_low, value: 20}}
    - {t: 16200, unstuck: tb_low}
    - {t: 18000, dead_flow_pump: true}
    - {t: 19800, set: {path: !P heat.s.heat.temp.cmd, value: 38}}

Times are seconds of simulated time. ``set`` writes a MoaT-Link item, as
an operator would.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from moat.util import yload

from .config import PlantCfg
from .plant import Plant

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path as FSPath

    from moat.lib.path import Path

    from collections.abc import Mapping

__all__ = ["Event", "Scenario"]

KINDS = frozenset(("dhw", "error", "stale", "fresh", "stuck", "unstuck", "dead_flow_pump", "set"))
"""The event kinds a scenario may use."""


@dataclass(order=True)
class Event:
    """One scheduled change."""

    t: float
    kind: str
    value: Any = field(compare=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Event:
        """Build from ``{t: …, <kind>: <value>}``."""
        data = dict(data)
        t = data.pop("t")
        if len(data) != 1 or (kind := next(iter(data))) not in KINDS:
            raise ValueError(f"Event needs one of {sorted(KINDS)}: {data!r}")
        return cls(float(t), kind, data[kind])

    def apply(self, plant: Plant) -> tuple[Path, Any] | None:
        """
        Apply the event to the plant.

        Returns:
            The ``(path, value)`` to write for a ``set`` event, else `None`.
        """
        v = self.value
        f = plant.faults
        match self.kind:
            case "dhw":
                plant.add_dhw(plant.now, v["duration"], v["lpm"])
            case "error":
                if v["code"]:
                    plant.inject_error(v["path"], v["code"], v.get("block", True))
                else:
                    plant.clear_error(v["path"])
            case "stale":
                f.stale.add(v)
            case "fresh":
                f.stale.discard(v)
            case "stuck":
                f.stuck[v["sensor"]] = v["value"]
            case "unstuck":
                f.stuck.pop(v, None)
            case "dead_flow_pump":
                f.dead_flow_pump = bool(v)
            case "set":
                return v["path"], v["value"]
        return None


@dataclass
class Scenario:
    """A plant setup plus a schedule of events."""

    plant: dict[str, Any] = field(default_factory=dict)
    """Overrides of the :class:`~moat.dev.heat.sim.config.PlantCfg` defaults."""

    seed: int = 0
    """Random seed of the plant."""

    events: list[Event] = field(default_factory=list)
    """The schedule, sorted by time."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Scenario:
        """Build from a mapping, as read from a scenario file."""
        unknown = set(data) - {"plant", "seed", "events"}
        if unknown:
            raise KeyError(f"Unknown scenario keys: {sorted(unknown)}")
        events = sorted(Event.from_dict(e) for e in data.get("events", ()))
        return cls(dict(data.get("plant", {})), int(data.get("seed", 0)), events)

    @classmethod
    def load(cls, path: FSPath) -> Scenario:
        """Read a scenario file."""
        with path.open() as f:
            return cls.from_dict(yload(f, attr=True) or {})

    def make_plant(self) -> Plant:
        """A new plant set up for this scenario."""
        return Plant(PlantCfg.from_dict(self.plant), seed=self.seed)

    def due(self, now: float) -> list[Event]:
        """Remove and return the events that are due at time ``now``."""
        n = 0
        while n < len(self.events) and self.events[n].t <= now:
            n += 1
        res, self.events = self.events[:n], self.events[n:]
        return res
