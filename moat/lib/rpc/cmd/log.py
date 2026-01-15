"""
Message logging.
"""

from __future__ import annotations

from moat.lib.micro import AC_use, TaskGroup, idle, log
from moat.lib.rpc import BaseFwdCmd, HandlerStream, Msg, MsgSender

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.util import attrdict
    from moat.lib.path import PathElem


class _LogStream(HandlerStream):
    other: _LogStream

    async def read_stream(self):
        """
        Stream reader.
        """
        while True:
            try:
                msg = await self.msg_out()
            except EOFError:
                self.other._log_writer.cancel()  # noqa:SLF001
                return
            await self.other.msg_in(msg)

    async def write_stream(self):
        """
        Stream writer. No-op.
        """
        async with TaskGroup() as self._log_writer:
            # taskgroup only used for its cancel scope
            await idle()
        raise EOFError


class Logger(BaseFwdCmd):
    """This is the handler for messages that forwards them to the stream."""

    def __init__(self, cfg: attrdict):
        super().__init__(cfg)
        self.prefix = cfg.get("prefix", "Msg")

    @property
    def root(self):  # noqa:D102
        return self

    @property
    def sender(self):  # noqa:D102
        return self._sender

    async def setup(self):  # noqa:D102
        await super().setup()
        self.s1 = _LogStream(self.real_root, logger=self._log)
        self.s2 = _LogStream(self.app)
        self.s1.other = self.s2
        self.s2.other = self.s1
        self._sender = MsgSender(self.s2)
        await AC_use(self, self.s1)
        await AC_use(self, self.s2)

    async def handle(self, msg: Msg, rcmd: list[PathElem]) -> None:
        "Forward"
        await self.s1.handle(msg, rcmd)

    def _log(self, m, *a):
        log(f"{self.prefix}:{m}", *a)
