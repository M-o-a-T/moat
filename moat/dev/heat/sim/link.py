"""
MoaT-Link adapter of the plant simulator.

Publishes the plant's sensor readings at their real MoaT-Link paths and
feeds the commands written to MoaT-Link back into the plant, so that the
heat units (or an operator) can run against a simulated plant. See
HEAT.md §5.3.
"""

from __future__ import annotations

import anyio
import logging
from math import inf

from moat.dev.heat.config import ServiceCfg, load_config
from moat.dev.heat.link import PWM_UNIT, Inputs, Reader, Writer
from moat.lib.path import P
from moat.util.time import time

from .loop import REFRESH
from .paths import INPUT_PATHS, SENSOR_PATHS, sensor_items
from .scenario import Scenario

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import TaskStatus

    from moat.lib.path import Path
    from moat.link.client import LinkSender

    from .plant import Plant

    from collections.abc import Mapping

__all__ = ["SimLink"]

_logger = logging.getLogger(__name__)


class SimLink:
    """
    Runs a plant simulator on MoaT-Link.

    Every ``dt / scale`` real seconds, the plant takes the latest commands,
    advances by ``dt`` simulated seconds, and its changed sensor readings
    are published (retained). A sensor that a scenario makes stale stops
    being published, so its MoaT-Link timestamp ages.

    Args:
        link: The MoaT-Link client.
        scenario: The plant setup and event schedule.
        plant: The simulator; built from ``scenario`` if not given.
        dt: Simulated seconds per step.
        scale: Simulated seconds per real second.
        sensors: Plant sensor name → paths to publish it at.
        inputs: Plant input name → path to read it from.
        refresh: A steady reading is published again after this many
            seconds, as the Modbus poller does.
    """

    refresh: float
    """A steady reading is published again after this many seconds."""

    def __init__(
        self,
        link: LinkSender,
        scenario: Scenario | None = None,
        *,
        plant: Plant | None = None,
        dt: float = 10,
        scale: float = 1,
        sensors: Mapping[str, tuple[Path, ...]] = SENSOR_PATHS,
        inputs: Mapping[str, Path] = INPUT_PATHS,
        refresh: float = REFRESH,
    ) -> None:
        self.link = link
        self.scenario = scenario or Scenario()
        self.plant = plant or self.scenario.make_plant()
        self.dt = dt
        self.scale = scale
        self.sensors = sensors
        self.writer = Writer(link)
        self.inputs = Inputs()
        for name, path in inputs.items():
            self.inputs.add(name, Reader[Any](link, path))
        self._errors: set[str] = set()
        self.refresh = refresh
        self._sent: dict[Path, float] = {}

    async def publish(self) -> None:
        """Publish the plant's changed sensor readings, and steady ones every `refresh` seconds."""
        now = time()
        for path, value in sensor_items(self.plant.sensors(), self.sensors, self._errors):
            if value is None:
                await self.link.d_set(path, retain=True)
                continue
            force = now - self._sent.get(path, -inf) >= self.refresh
            if await self.writer.set(path, value, force=force):
                self._sent[path] = now

    def apply_inputs(self) -> None:
        """Copy the latest commands into the plant."""
        inp = self.plant.inputs
        for name, value in self.inputs.snapshot().items():
            if value is not None:
                setattr(inp, name, value)

    async def step(self) -> None:
        """Run scheduled events, advance the plant by one step, publish."""
        for ev in self.scenario.due(self.plant.now):
            _logger.info("t=%d: %s %r", self.plant.now, ev.kind, ev.value)
            if (w := ev.apply(self.plant)) is not None:
                await self.writer.set(*w, force=True)
        self.apply_inputs()
        self.plant.step(self.dt)
        await self.publish()

    async def run(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """
        Run the simulator until cancelled.

        The simulator stands in for the PWM daemon (it reads the PWM value
        itself), so it announces that daemon's service: the pump unit
        doesn't start the heat pump without it.
        """
        svc = await load_config(self.link, "service", ServiceCfg)
        async with (
            self.link.announcing(P("heat") / PWM_UNIT, host=svc.host, wait=True) as srv,
            anyio.create_task_group() as tg,
        ):
            await tg.start(self.inputs.run)
            await self.publish()
            srv.set()
            task_status.started()

            t0 = anyio.current_time()
            n = 0
            while True:
                n += 1
                await anyio.sleep_until(t0 + n * self.dt / self.scale)
                await self.step()
