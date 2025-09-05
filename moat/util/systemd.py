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

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .path import Path

@asynccontextmanager
async def as_service(obj=None):
    """
    This async context manager provides readiness and keepalive messages to
    systemd.

    Arguments:
        obj: command context. Needs a ``debug`` attribute.
        host: 

    The CM yields a (duck-typed) event whose ``set`` method will
    trigger a ``READY=1`` mesage to systemd.
    """

    from moat.util import Path

    async def run_keepalive(usec):
        usec /= 1_500_000  # 2/3rd of usec ⇒ sec
        pid = os.getpid()
        while os.getpid() == pid:
            if notify is not None:
                notify("WATCHDOG=1")
            await anyio.sleep(usec)

    async def run_announce(link, srv, rm):
        await rm.evt.wait()
        await link.d_set(P("run.host")+srv, dict(id=link.id), retain=True)

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
            self.evt = anyio.Event()

        def set(self):  # pylint:disable=missing-function-docstring
            self.evt.set()
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
        if (link := getattr(obj,"link", None)) is not None and (host := getattr(obj,"host",None)) is None and int(os.envieon.get("SYSTEMD_EXEC_PID","0")) == os.getpid():
            cg = await anyio.Path("/proc/self/cgroup").read_text()
            for cge in cg.strip().split("/"):
                if cge.endsith(".service"):
                    cge = cge[:-8]
                    hi = cge.split("@",1)
                    if hi[0] == "user":
                        break  # ignore
                    host = [Path(os.uname().nodename)]
                    if len(hi) != 1 or hi[0] != "moat-link-host":
                        host += hi
                    break

        usec = need_keepalive()
        if usec:
            tg.start_soon(run_keepalive, usec)
        try:
            rm = RunMsg(tg, obj)
            if link is not None:
                tg.start_soon(run_announce, link, host, rm)
            yield rm
        finally:
            tg.cancel_scope.cancel()
