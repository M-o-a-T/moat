"""
This module contains the systemd service helper.
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


class RunMsg(anyio.abc.TaskStatus):
    """A helper to signal readiness or status updates to systemd.

    It also duck-types as :class:`anyio.abc.TaskStatus.`
    """

    def __init__(self, tg, obj):
        self.tg = tg
        self.obj = obj
        self.evt = anyio.Event()

    def set(self):  # pylint:disable=missing-function-docstring
        self.evt.set()
        if notify is not None:
            notify("READY=1")
        if self.obj is not None and self.obj.debug:
            print("Running.")

    def started(self, value: anyio.abc.T_Contra | None = None):
        "mock task_status.started"
        if value is not None:
            raise ValueError("value is ignored")
        self.set()


@asynccontextmanager
async def as_service(obj=None):
    """
    This async context manager provides readiness and keepalive messages to
    systemd.

    Arguments:
        obj: command context. Needs a ``debug`` attribute.

    The ACM yields a (duck-typed) event whose ``set`` method will
    trigger the ``READY=1`` mesage to systemd.
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
            # prevent the watchdog from restarting / running concurrently
            os.environ["WATCHDOG_PID"] = "0"
            return int(os.environ.get("WATCHDOG_USEC", "0"))
        return 0

    async with anyio.create_task_group() as tg:
        usec = need_keepalive()
        if usec:
            tg.start_soon(run_keepalive, usec)
        try:
            yield RunMsg(tg, obj)
        finally:
            tg.cancel_scope.cancel()
