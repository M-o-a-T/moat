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

    scope = None

    async def _run(proc, args, kw, evt):
        """
        Helper for starting a task within a cancel scope.
        """
        nonlocal scope
        async with anyio.open_cancel_scope() as sc:
            scope = sc
            await evt.set()
            await proc(*args, **kw)

    evt = anyio.create_event()
    await taskgroup.spawn(_run, proc, args, kw, evt)
    await evt.wait()
    return scope
