"""
Closed-loop runner: the plant simulator and unit cores, wired by path.

Everything runs in-process and synchronously in simulated time; there is
no MoaT-Link, no event loop and no clock (HEAT.md §5.2). Values travel
over a dict keyed by MoaT-Link path, so cores see exactly the inputs
their Link adapter would give them.

A tick: the plant reads its commands from the bus and advances; its
sensor readings are published; then every core whose inputs changed, or
whose wake-up time has come, is stepped, and its outputs are published.
Cores are stepped repeatedly within a tick until nothing changes any
more, so a chain of units settles in one tick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import inf

from moat.util import NotGiven
from moat.dev.heat.config import make_config
from moat.dev.heat.link import Override
from moat.util.time import patch_clock

from .paths import INPUT_PATHS, SENSOR_PATHS, sensor_items
from .plant import Plant

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from moat.dev.heat.link import Reader
    from moat.dev.heat.state import State
    from moat.dev.heat.unit import Core, Unit
    from moat.lib.path import Path

    from .config import PlantCfg

    from collections.abc import Callable, Mapping

__all__ = ["WALL0", "ClosedLoop", "CoreSlot"]

WALL0 = 1_767_567_600.0  # 2026-01-05 00:00 CET, a Monday
"""Default wall-clock time at simulated time 0."""

MAX_ROUNDS = 20
"""How often cores may be stepped within one tick before we give up settling."""


@dataclass
class CoreSlot:
    """A core in the loop, with its readers."""

    name: str
    core: Core[Any]
    readers: dict[str, Reader[Any]]
    cfg: Any = None
    state: State | None = None
    wake_at: float = 0.0
    steps: int = 0
    saves: int = 0
    dirty: bool = True
    by_path: dict[Path, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for k, r in self.readers.items():
            self.by_path.setdefault(r.path, []).append(k)
            r.on_change = self._changed

    def _changed(self) -> None:
        self.dirty = True


class ClosedLoop:
    """
    The plant simulator plus unit cores.

    Args:
        plant: The simulator; a new one is built from ``cfg``/``seed`` if
            not given.
        cfg: Plant configuration, if ``plant`` is not given.
        seed: Plant seed, if ``plant`` is not given.
        sensors: Plant sensor name → paths to publish it at.
        inputs: Plant input name → path to read it from.
        wall0: Wall-clock time at simulated time 0 (for message
            timestamps, override expiry and PID persistence).
    """

    def __init__(
        self,
        plant: Plant | None = None,
        *,
        cfg: PlantCfg | None = None,
        seed: int = 0,
        sensors: Mapping[str, tuple[Path, ...]] = SENSOR_PATHS,
        inputs: Mapping[str, Path] = INPUT_PATHS,
        wall0: float = WALL0,
    ) -> None:
        self.plant = plant or Plant(cfg, seed=seed)
        self.sensors = sensors
        self.inputs = inputs
        self.wall0 = wall0
        self.bus: dict[Path, Any] = {}
        self.ts: dict[Path, float] = {}
        self.slots: list[CoreSlot] = []
        self.writes: list[tuple[float, Path, Any]] = []
        self.watchers: list[Callable[[float, Path, Any], None]] = []
        self._errors: set[str] = set()
        self.publish_sensors()

    # time

    @property
    def now(self) -> float:
        """Simulated (monotonic) time."""
        return self.plant.now

    @property
    def wall(self) -> float:
        """Simulated wall-clock time."""
        return self.wall0 + self.plant.now

    # the bus

    def set(self, path: Path, value: Any) -> bool:
        """
        Publish a value; returns whether it changed.

        ``None`` (or ``NotGiven``) deletes the item.
        """
        with self.clock():
            return self._set(path, value)

    def _set(self, path: Path, value: Any) -> bool:
        if value is NotGiven:
            value = None
        if path in self.bus and self.bus[path] == value:
            return False
        if value is None and path not in self.bus:
            return False
        if value is None:
            del self.bus[path]
        else:
            self.bus[path] = value
        self.ts[path] = self.wall
        for w in self.watchers:
            w(self.now, path, value)
        for slot in self.slots:
            for name in slot.by_path.get(path, ()):
                slot.readers[name].feed(value, self.wall)
        return True

    def get(self, path: Path, default: Any = None) -> Any:
        """The current value of an item."""
        return self.bus.get(path, default)

    def publish_sensors(self) -> None:
        """Copy the plant's sensor readings to the bus."""
        for p, v in sensor_items(self.plant.sensors(), self.sensors, self._errors):
            self.set(p, v)

    def apply_inputs(self) -> None:
        """Copy commands from the bus to the plant."""
        inp = self.plant.inputs
        for name, path in self.inputs.items():
            if path in self.bus:
                setattr(inp, name, self.bus[path])

    # cores

    def add_core(
        self,
        name: str,
        core: Core[Any],
        readers: Mapping[str, Reader[Any]],
        cfg: Any = None,
        state: State | None = None,
    ) -> CoreSlot:
        """
        Add a core with its readers (as the unit's ``make_inputs`` would build them).

        Current bus values are fed to the readers at once.
        """
        slot = CoreSlot(name, core, dict(readers), cfg=cfg, state=state, wake_at=self.now)
        for r in slot.readers.values():
            if r.path in self.bus:
                r.feed(self.bus[r.path], self.ts[r.path])
            else:
                r.feed(None, None)
        self.slots.append(slot)
        return slot

    def add_unit(
        self, unit: type[Unit[Any, Any]], cfg: Any = NotGiven, state: State | None = None
    ) -> CoreSlot:
        """
        Add a unit's core, configured like its adapter would do it.

        Args:
            unit: The unit's adapter class.
            cfg: The unit's config item (merged with the package defaults),
                or a config instance.
            state: The unit's initial state; default: a fresh one.
        """
        if not isinstance(cfg, unit.cfg_model):
            cfg = make_config(unit.name, unit.cfg_model, cfg)
        if state is None:
            state = unit.state_model()
        adapter = unit.__new__(unit)
        adapter.link = None
        readers = adapter.make_inputs(cfg)
        core = adapter.make_core(cfg, state, self.now)
        return self.add_core(unit.name, core, readers, cfg=cfg, state=state)

    def update_cfg(self, slot: CoreSlot, cfg: Any) -> None:
        """Change a core's configuration, as a config update would."""
        slot.cfg = cfg
        slot.core.update_cfg(cfg)
        slot.dirty = True

    def _expire_overrides(self) -> None:
        for slot in self.slots:
            for r in slot.readers.values():
                if (
                    isinstance(r, Override)
                    and r.expires is not None
                    and r.expires <= self.wall
                    and r.value is not None
                ):
                    r.feed(self.bus.get(r.path), self.ts.get(r.path))

    def _step_cores(self) -> None:
        for _ in range(MAX_ROUNDS):
            busy = False
            for slot in self.slots:
                if not slot.dirty and slot.wake_at > self.now:
                    continue
                slot.dirty = False
                snap = {k: r.value for k, r in slot.readers.items()}
                res = slot.core.step(snap, self.now)
                slot.steps += 1
                if res.save or res.save_now:
                    slot.saves += 1
                slot.wake_at = inf if res.wake_in is None else self.now + res.wake_in
                for path, value in res.outputs.items():
                    if self.set(path, value):
                        self.writes.append((self.now, path, value))
                        busy = True
            if not busy and not any(s.dirty for s in self.slots):
                return
        raise RuntimeError(f"Cores did not settle within {MAX_ROUNDS} rounds at t={self.now}")

    # running

    def step(self, dt: float) -> None:
        """One tick of ``dt`` seconds."""
        with self.clock():
            self.apply_inputs()
            self.plant.step(dt)
            self.publish_sensors()
            self._expire_overrides()
            self._step_cores()

    def run(
        self, duration: float, dt: float = 10, cb: Callable[[ClosedLoop], None] | None = None
    ) -> None:
        """Run for ``duration`` seconds; call ``cb(loop)`` after every tick."""
        end = self.now + duration
        with self.clock():
            self._step_cores()  # initial step, before the plant moves
            if cb is not None:
                cb(self)
            while self.now < end - 1e-9:
                self.step(min(dt, end - self.now))
                if cb is not None:
                    cb(self)

    def clock(self) -> AbstractContextManager[None]:
        """Context: ``moat.util.time.time()`` returns simulated wall-clock time."""
        return patch_clock(time=lambda: self.wall)
