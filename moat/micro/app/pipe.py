"""
App to open a channel to a process.
"""

from __future__ import annotations

from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM
from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg
from moat.micro.proto.stream import ProcessBuf
from moat.micro.stacks.console import console_stack
from moat.util.compat import AC_use


class ProcessCmd(BaseCmdMsg):
    """
    Channel to a process that handles MoaT messages
    """

    argv = None
    path = None

    async def stream(self):  # noqa:D102
        argv = self.cfg["command"] if self.argv is None else self.argv
        path = self.cfg.get("path") if self.path is None else self.path
        if path is None and argv[0][0] == "/":
            path = argv[0]

        proc = ProcessBuf(argv, executable=path)
        return await AC_use(self, console_stack(proc, cfg=self.cfg))


class ProcessIO(BaseCmdBBM):
    """
    Byte channel to a process that handles arbitrary MaoT messages
    """

    argv = None
    path = None

    async def stream(self):  # noqa:D102
        argv = self.cfg["command"] if self.argv is None else self.argv
        path = self.cfg.get("path") if self.path is None else self.path
        if path is None and argv[0][0] == "/":
            path = argv[0]

        proc = ProcessBuf(argv, executable=path)
        return await AC_use(self, proc)
