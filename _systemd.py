"""
This module contains various helper functions and classes.
"""
import os
from contextlib import asynccontextmanager

import anyio

__all__ = ["as_service"]


@asynccontextmanager
async def as_service(obj=None):
    """
    This async context manager provides readiness and keepalive messages to
    systemd.

    Arguments:
        obj: command context. Needs a ``debug`` attribute.

    The CM yields a (duck-typed) event whose async ``set`` method will
    trigger a ``READY=1`` mesage to systemd.
    """
    from systemd.daemon import notify  # pylint: disable=no-name-in-module

    async def run_keepalive(usec):
        usec /= 1_500_000  # 2/3rd of usec ⇒ sec
        pid = os.getpid()
        while os.getpid() == pid:
            notify("WATCHDOG=1")
            await anyio.sleep(usec)

    def need_keepalive():
        pid = os.getpid()
        epid = int(os.environ.get("WATCHDOG_PID", pid))
        if pid == epid:
            return int(os.environ.get("WATCHDOG_USEC", 0))

    class RunMsg:
        def __init__(self, obj):
            self.obj = obj

        def set(self):
            # TODO: this should be async (set flag and separate thread)
            notify("READY=1")
            if self.obj is not None and self.obj.debug:
                print("Running.")

    async with anyio.create_task_group() as tg:
        usec = need_keepalive()
        if usec:
            tg.spawn(run_keepalive, usec)
        try:
            yield RunMsg(obj)
        finally:
            with anyio.fail_after(2, shield=True):
                tg.cancel_scope.cancel()
