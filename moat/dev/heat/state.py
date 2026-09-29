"""
Persistent per-unit state of the heat controller.

Each unit owns ``app.heat.<unit>.state``. See HEAT.md §2.3.
"""

from __future__ import annotations

import anyio
import logging

from moat.lib.config.base import BaseModel
from moat.lib.path import P
from moat.util.time import loop_time, time

from .pid import T_OFFSET

from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from anyio.abc import TaskStatus

    from moat.lib.path import Path
    from moat.link.client import LinkSender

__all__ = ["State", "StateStore", "state_path"]

_logger = logging.getLogger(__name__)


class State(BaseModel):
    """Base class of every unit's persistent state."""


S = TypeVar("S", bound=State)


def state_path(unit: str) -> Path:
    """The MoaT-Link path of a unit's persistent state."""
    return P("app.heat") / unit / "state"


class StateStore(Generic[S]):
    """
    Loads a unit's state and saves it when it changes.

    Monotonic timestamps in the state (``pid.MonoTime`` fields)
    are persisted as wall-clock time.

    Call :meth:`load`, then start :meth:`run` in a task group. After
    modifying :attr:`state`, call :meth:`changed`. Pending changes are
    written when :meth:`run` ends.

    Args:
        link: The MoaT-Link client.
        unit: The unit's name.
        model: The unit's state model.
        save_delay: How long to collect changes before writing them, in
            seconds.
    """

    state: S
    """The current state. Valid after :meth:`load`."""

    save_delay: float
    """How long to collect changes before writing them, in seconds."""

    def __init__(
        self, link: LinkSender, unit: str, model: type[S], save_delay: float = 10.0
    ) -> None:
        self.link = link
        self.path = state_path(unit)
        self.model = model
        self.save_delay = save_delay
        self._dirty = anyio.Event()
        self._now = anyio.Event()

    async def load(self) -> S:
        """
        Read the state from MoaT-Link.

        Missing or invalid state is replaced by the model's defaults.
        """
        try:
            data = await self.link.d_get(self.path)
        except KeyError:
            self.state = self.model()
        else:
            try:
                self.state = self.model.model_validate(data, context=self._ctx())
            except Exception as exc:
                _logger.warning("Invalid state at %s, using defaults: %r", self.path, exc)
                self.state = self.model()
        return self.state

    def changed(self, immediate: bool = False) -> None:
        """
        Mark the state as modified.

        Args:
            immediate: Write it now instead of after :attr:`save_delay`,
                e.g. for a pump state transition.
        """
        self._dirty.set()
        if immediate:
            self._now.set()

    async def save(self) -> None:
        """
        Write the state, and wait until the server has it.
        """
        await self.link.d_set(self.path, self.state.model_dump(context=self._ctx()), retain=True)
        await self.link.i_sync()

    @staticmethod
    def _ctx() -> dict[str, float]:
        """Conversion between persisted wall-clock and in-memory monotonic time."""
        return {T_OFFSET: time() - loop_time()}

    async def run(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """Save the state whenever it has changed."""
        task_status.started()
        try:
            while True:
                await self._dirty.wait()
                with anyio.move_on_after(self.save_delay):
                    await self._now.wait()
                self._dirty = anyio.Event()
                self._now = anyio.Event()
                await self.save()
        finally:
            if self._dirty.is_set():
                with anyio.CancelScope(shield=True), anyio.move_on_after(2):
                    await self.save()
