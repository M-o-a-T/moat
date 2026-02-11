"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

import anyio

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import TaskGroup, TaskStatus

    from collections.abc import Awaitable, Callable

__all__ = ["spawn"]


async def spawn(
    taskgroup: TaskGroup,
    proc: Callable[..., Awaitable[Any]],
    *args: Any,
    **kw: Any,
) -> anyio.CancelScope:
    """
    Run a task within this object's task group.

    Returns:
        a cancel scope you can use to stop the task.
    """

    async def _run(
        proc: Callable[..., Awaitable[Any]],
        args: tuple[Any, ...],
        kw: dict[str, Any],
        *,
        task_status: TaskStatus[anyio.CancelScope],
    ) -> None:
        """
        Helper for starting a task within a cancel scope.
        """
        with anyio.CancelScope() as sc:
            task_status.started(sc)
            await proc(*args, **kw)

    return await taskgroup.start(_run, proc, args, kw)
