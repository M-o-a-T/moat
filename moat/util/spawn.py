"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

import anyio

from typing import TYPE_CHECKING, ParamSpec

if TYPE_CHECKING:
    from anyio.abc import TaskGroup, TaskStatus

    from collections.abc import Awaitable, Callable

__all__ = ["spawn"]

P = ParamSpec("P")


async def spawn(
    taskgroup: TaskGroup,
    proc: Callable[P, Awaitable[object]],
    *args: P.args,
    **kw: P.kwargs,
) -> anyio.CancelScope:
    """
    Run a task within this object's task group.

    Returns:
        a cancel scope you can use to stop the task.
    """

    async def _run(
        *,
        task_status: TaskStatus[anyio.CancelScope],
    ) -> None:
        """
        Helper for starting a task within a cancel scope.
        """
        with anyio.CancelScope() as sc:
            task_status.started(sc)
            await proc(*args, **kw)

    return await taskgroup.start(_run)
