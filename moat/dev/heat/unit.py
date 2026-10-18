"""
The heat controller's unit structure.

A unit is a sans-IO core plus a thin MoaT-Link adapter (HEAT.md §2.1).
The core decides; it gets the current inputs and the monotonic time and
returns a `Step`. The adapter, a `Unit` subclass, does all I/O: it loads
config and state, watches the inputs, calls the core, writes its outputs,
saves its state and announces the service.
"""

from __future__ import annotations

import anyio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from math import inf

from moat.util import time as mtime
from moat.lib.path import P

from .config import ServiceCfg, UnitCfg, load_config, unit_config
from .link import Inputs, Writer
from .state import State, StateStore

from typing import TYPE_CHECKING, Any, ClassVar, Generic, Protocol, TypeVar

if TYPE_CHECKING:
    from anyio.abc import TaskGroup, TaskStatus

    from moat.lib.path import Path
    from moat.link.client import LinkSender

    from .link import Reader

    from collections.abc import Callable

__all__ = ["Core", "Step", "Unit"]

_logger = logging.getLogger(__name__)

C = TypeVar("C", bound=UnitCfg)
S = TypeVar("S", bound=State)
C_contra = TypeVar("C_contra", bound=UnitCfg, contravariant=True)


@dataclass
class Step:
    """The result of one core step."""

    outputs: dict[Path, Any] = field(default_factory=dict)
    """Values to write, by path. Unchanged values are not re-sent."""

    wake_in: float | None = None
    """Call the core again after this many seconds, even if no input changes."""

    save: bool = False
    """The state has changed and should be saved."""

    save_now: bool = False
    """The state has changed and must be saved right away."""

    force: bool = False
    """Write all outputs, even those that haven't changed."""

    act: Any = None
    """Something for the adapter to do (see `Unit.act`)."""


class Core(Protocol[C_contra]):
    """The sans-IO part of a unit."""

    def update_cfg(self, cfg: C_contra) -> None:
        """Apply a changed configuration."""
        ...

    def step(self, inputs: dict[str, Any], now: float) -> Step:
        """
        Decide what to do.

        Args:
            inputs: The current value of every input, by name; `None` if
                unknown. ``_age`` maps every input's name to the age of
                its value in seconds (`~moat.dev.heat.link.Reader.age`).
                Units with :attr:`Unit.local_time` also get ``local``,
                the local date and time (a naive `datetime`).
            now: The current monotonic time.
        """
        ...


class Unit(Generic[C, S]):
    """
    The MoaT-Link adapter of a unit.

    Subclasses set :attr:`name`, :attr:`cfg_model` and :attr:`state_model`
    and implement :meth:`make_core` and :meth:`make_inputs`.

    Args:
        link: The MoaT-Link client.
        save_delay: Passed to :class:`~moat.dev.heat.state.StateStore`.
    """

    name: ClassVar[str]
    """The unit's name, e.g. ``pump``."""

    cfg_model: type[C]
    """The unit's configuration model."""

    state_model: type[S]
    """The unit's state model."""

    local_time: ClassVar[bool] = False
    """The core gets the local date and time as input ``local``."""

    service: ServiceCfg = ServiceCfg()
    """The shared service settings; loaded by :meth:`run` before the inputs are built."""

    core: Core[C] | None = None
    """The running core."""

    def __init__(self, link: LinkSender, save_delay: float = 10.0) -> None:
        self.link = link
        self.store = StateStore(link, self.name, self.state_model, save_delay=save_delay)
        self.writer = Writer(link)
        self._wake = anyio.Event()
        self._new_cfg: C | None = None

    def make_core(self, cfg: C, state: S, now: float) -> Core[C]:
        """Create the core."""
        raise NotImplementedError

    def make_inputs(self, cfg: C) -> dict[str, Reader[Any]]:
        """Create the readers for the core's inputs, by name."""
        raise NotImplementedError

    def check(self, inputs: dict[str, Any], now: float) -> float | None:
        """
        Look at the inputs before the core does; raise to stop the unit.

        The inputs may be amended. If the result is a number, the unit is
        stepped again after (at most) that many seconds.

        The default does nothing.
        """

    async def act(self, what: Any) -> None:
        """
        Do what the core asked for in `Step.act`; the core is stepped again
        afterwards. The default does nothing.
        """

    async def abort(self, exc: BaseException) -> None:
        """
        Clean up after the unit's main loop ended with ``exc``.

        Called shielded, while the service is still announced; ``exc`` is
        re-raised afterwards. The default does nothing.
        """

    def _trigger(self) -> None:
        self._wake.set()

    async def _watch_cfg(self, *, task_status: TaskStatus[C]) -> None:
        first = True
        async for cfg in unit_config(self.link, self.name, self.cfg_model):
            if first:
                task_status.started(cfg)
                first = False
            else:
                self._new_cfg = cfg
                self._trigger()

    async def _start_inputs(self, tg: TaskGroup, cfg: C) -> tuple[Inputs, anyio.CancelScope]:
        inputs = Inputs(on_change=self._trigger)
        for k, r in self.make_inputs(cfg).items():
            inputs.add(k, r)
        return inputs, await tg.start(self._run_inputs, inputs)

    @staticmethod
    async def _run_inputs(inputs: Inputs, *, task_status: TaskStatus[anyio.CancelScope]) -> None:
        with anyio.CancelScope() as sc:
            async with anyio.create_task_group() as tg:
                await tg.start(inputs.run)
                task_status.started(sc)

    async def run(
        self,
        *,
        force: bool = False,
        on_wait: Callable[[str | None], None] | None = None,
        task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """
        Run the unit.

        Args:
            force: Take the unit's service over from whoever runs it.
                Otherwise, wait until nobody else does.
            on_wait: Called when the unit has to wait for its service; see
                :func:`moat.link.announce.announcing`.
        """
        self.service = svc = await load_config(self.link, "service", ServiceCfg)
        state = await self.store.load()

        async with (
            self.link.announcing(
                P("heat") / self.name, host=svc.host, force=force, wait=True, on_wait=on_wait
            ) as srv,
            anyio.create_task_group() as tg,
        ):
            await tg.start(self.store.run)
            cfg: C = await tg.start(self._watch_cfg)
            self.core = core = self.make_core(cfg, state, anyio.current_time())
            inputs, scope = await self._start_inputs(tg, cfg)
            srv.set()
            task_status.started()

            try:
                await self._loop(tg, core, inputs, scope)
            except BaseException as exc:
                with anyio.CancelScope(shield=True):
                    await self.abort(exc)
                raise

    async def _loop(
        self, tg: TaskGroup, core: Core[C], inputs: Inputs, scope: anyio.CancelScope
    ) -> None:
        wake_in: float | None = 0
        while True:
            with anyio.move_on_after(inf if wake_in is None else wake_in):
                await self._wake.wait()
            self._wake = anyio.Event()

            if (new := self._new_cfg) is not None:
                self._new_cfg = None
                core.update_cfg(new)
                scope.cancel()
                inputs, scope = await self._start_inputs(tg, new)

            snap = inputs.snapshot()
            snap["_age"] = inputs.ages(mtime.time())
            if self.local_time:
                snap["local"] = datetime.fromtimestamp(mtime.time())  # noqa: DTZ006
            now = anyio.current_time()
            recheck = self.check(snap, now)
            res = core.step(snap, now)
            watched = {r.path: r for r in inputs.readers.values()}
            for path, value in res.outputs.items():
                # a path we also watch may have been changed by someone
                # else since we last wrote it
                r = watched.get(path)
                await self.writer.set(
                    path, value, force=res.force or (r is not None and r.differs(value))
                )
            if res.save or res.save_now:
                self.store.changed(immediate=res.save_now)
            wake_in = res.wake_in
            if recheck is not None and (wake_in is None or recheck < wake_in):
                wake_in = recheck
            if res.act is not None:
                await self.act(res.act)
                wake_in = 0
