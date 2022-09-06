"""
This module contains various helper functions and classes.
"""
import anyio

__all__ = ["spawn"]


async def spawn(taskgroup, proc, *args, **kw):
    """
    Run a task within this object's task group.

    Returns:
        a cancel scope you can use to stop the task.
    """

    async def _run(proc, args, kw, *, task_status):
        """
        Helper for starting a task within a cancel scope.
        """
        with anyio.CancelScope() as sc:
            task_status.started(sc)
            await proc(*args, **kw)

    return await taskgroup.start(_run, proc, args, kw)
