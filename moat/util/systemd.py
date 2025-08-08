"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

import anyio
import os
from contextlib import asynccontextmanager

__all__ = ["as_service"]

try:
    from systemd.daemon import notify  # pylint: disable=no-name-in-module
except ImportError:
    notify = None


@asynccontextmanager
async def as_service(obj=None):
    """
    This async context manager provides readiness and keepalive messages to
    systemd.

    Arguments:
        obj: command context. Needs a ``debug`` attribute.

    The CM yields a (duck-typed) event whose ``set`` method will
    trigger a ``READY=1`` mesage to systemd.
    """

    async def run_keepalive(usec):
        usec /= 1_500_000  # 2/3rd of usec ⇒ sec
        pid = os.getpid()
        while os.getpid() == pid:
            if notify is not None:
                notify("WATCHDOG=1")
            await anyio.sleep(usec)

    def need_keepalive():
        pid = os.getpid()
        epid = int(os.environ.get("WATCHDOG_PID", pid))
        if pid == epid:
            return int(os.environ.get("WATCHDOG_USEC", 0))
        return 0

    class RunMsg:
        """A fake event that signals readiness"""

        def __init__(self, tg, obj):
            self.tg = tg
            self.obj = obj

        def set(self):  # pylint:disable=missing-function-docstring
            if notify is not None:
                notify("READY=1")
            if self.obj is not None and self.obj.debug:
                print("Running.")

        def started(self, data=None):
            "mock task_status.started"
            if data is not None:
                raise ValueError("data is ignored")
            self.set()

    async with anyio.create_task_group() as tg:
        usec = need_keepalive()
        if usec:
            tg.start_soon(run_keepalive, usec)
        try:
            yield RunMsg(tg, obj)
        finally:
            tg.cancel_scope.cancel()
