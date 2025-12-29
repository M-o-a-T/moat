"""RPC infrastructure for remote REPL access."""

from __future__ import annotations

from moat.lib.rpc import MsgHandler

TYPE_CHECKING = False

if TYPE_CHECKING:
    from .console import Console


class MsgConsole(MsgHandler):
    """
    RPC handler that wraps a Console instance and exposes its methods via cmd_* handlers.

    This allows remote access to console operations via the MsgSender interface.
    """

    def __init__(self, console: Console):
        self.console = console

    async def cmd_rd(self, n: int) -> bytes:
        """Read up to n bytes from the console."""
        return await self.console.rd(n)

    async def cmd_wr(self, data: bytes) -> None:
        """Write data to the console."""
        await self.console.wr(data)
