"""RPC infrastructure for remote REPL access."""

from __future__ import annotations

from moat.lib.rpc import MsgHandler

TYPE_CHECKING = False

if TYPE_CHECKING:
    from .console import Console, Event


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

    async def cmd_refresh(self, screen: list[str], xy: tuple[int, int]) -> None:
        """Refresh the console screen."""
        await self.console.refresh(screen, xy)

    async def cmd_prepare(self) -> None:
        """Prepare the console."""
        await self.console.prepare()

    async def cmd_restore(self) -> None:
        """Restore the console."""
        await self.console.restore()

    async def cmd_move_cursor(self, x: int, y: int) -> None:
        """Move the cursor."""
        await self.console.move_cursor(x, y)

    async def cmd_set_cursor_vis(self, visible: bool) -> None:
        """Set cursor visibility."""
        await self.console.set_cursor_vis(visible)

    async def cmd_getheightwidth(self) -> tuple[int, int]:
        """Get terminal height and width."""
        return await self.console.getheightwidth()

    async def cmd_get_event(self) -> Event:
        """Get the next event."""
        return await self.console.get_event()

    async def cmd_push_char(self, char: int | bytes) -> None:
        """Push a character to the event queue."""
        await self.console.push_char(char)

    async def cmd_beep(self) -> None:
        """Beep."""
        await self.console.beep()

    async def cmd_clear(self) -> None:
        """Clear the screen."""
        await self.console.clear()

    async def cmd_finish(self) -> None:
        """Finish console operations."""
        await self.console.finish()

    async def cmd_flushoutput(self) -> None:
        """Flush output."""
        await self.console.flushoutput()

    async def cmd_forgetinput(self) -> None:
        """Forget pending input."""
        await self.console.forgetinput()

    async def cmd_getpending(self) -> Event:
        """Get pending input."""
        return await self.console.getpending()

    async def cmd_repaint(self) -> None:
        """Repaint the screen."""
        await self.console.repaint()
