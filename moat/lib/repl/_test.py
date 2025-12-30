"""Testing utilities for moat.lib.repl."""

from __future__ import annotations

import anyio
from contextlib import asynccontextmanager

from .console import Console, Event

TYPE_CHECKING = False

if TYPE_CHECKING:
    from collections.abc import Callable


class MockConsole(Console, anyio.AsyncContextManagerMixin):
    """
    Mock console for testing that records actions and provides scripted input.

    User actions can be:
        float - delay in seconds before next action
        bytes - mock input to be returned by rd()

    Recorded actions include:
        ("wr", bytes) - data written via wr()
        ("rd", bytes) - number of bytes read via rd()
        ("action", str) - operations like "prepare", "restore", "raw", "cooked"
    """

    def __init__(
        self,
        term: str = "",
        encoding: str = "",
        user_actions: list[float | bytes] | None = None,
    ):
        super().__init__(-1, -1, term, encoding)
        self.user_actions = list(user_actions) if user_actions else []
        self.record: list[tuple[str, object]] = []
        self.input_buffer = b""
        self.output_buffer = b""
        self._height = 25
        self._width = 80

    @asynccontextmanager
    async def __asynccontextmanager__(self):
        """Async context manager for console lifecycle."""
        assert not self.record
        self.record.append(("action", "enter"))
        try:
            yield self
        finally:
            self.record.append(("action", "exit"))

    async def rd(self, n: int) -> bytes:
        """Read up to n bytes from mock input."""
        # Process user actions until we have input
        while not self.input_buffer and self.user_actions:
            action = self.user_actions.pop(0)
            if isinstance(action, float):
                await anyio.sleep(action)
            elif isinstance(action, bytes):
                self.input_buffer += action

        # Return available data
        result = self.input_buffer[:n]
        self.input_buffer = self.input_buffer[n:]

        self.record.append(("rd", result))
        return result

    async def wr(self, data: bytes) -> None:
        """Write data to mock output."""
        self.record.append(("wr", data))
        self.output_buffer += data

    async def prepare(self, reader: bool = True) -> None:
        """Mock prepare."""
        self.record.append(("action", "prepare" if reader else "prepare_raw"))
        self.screen = []
        self.height, self.width = self._height, self._width

    async def restore(self) -> None:
        """Mock restore."""
        self.record.append(("action", "restore"))

    async def refresh(self, screen: list[str], xy: tuple[int, int]) -> None:
        """Mock refresh."""
        self.record.append(("action", "refresh", screen, xy))

    async def move_cursor(self, x: int, y: int) -> None:
        """Mock move_cursor."""
        assert self.record[0] == ("action", "enter")
        assert ("action", "exit") not in self.record
        self.record.append(("action", "move_cursor", x, y))

    async def set_cursor_vis(self, visible: bool) -> None:
        """Mock set_cursor_vis."""
        self.record.append(("action", "set_cursor_vis", visible))

    async def getheightwidth(self) -> tuple[int, int]:
        """Return mock terminal size."""
        self.record.append(("action", "getheightwidth"))
        return (self._height, self._width)

    async def get_event(self) -> Event:
        """Get next event from mock input."""
        data = await self.rd(1)
        if not data:
            # No more input available, treat as EOF
            raise EOFError
        return Event(evt="key", data=data.decode(self.encoding, errors="replace"), raw=data)

    async def push_char(self, char: int | bytes) -> None:
        """Push character to mock input buffer."""
        if isinstance(char, int):
            char = bytes([char])
        self.input_buffer = char + self.input_buffer

    async def beep(self) -> None:
        """Mock beep."""
        self.record.append(("action", "beep"))

    async def clear(self) -> None:
        """Mock clear."""
        self.record.append(("action", "clear"))

    async def finish(self) -> None:
        """Mock finish."""
        self.record.append(("action", "finish"))

    async def flushoutput(self) -> None:
        """Mock flushoutput."""
        self.record.append(("action", "flushoutput"))

    async def forgetinput(self) -> None:
        """Mock forgetinput."""
        self.record.append(("action", "forgetinput"))

    async def getpending(self) -> Event:
        """Mock getpending."""
        self.record.append(("action", "getpending"))
        return Event(evt="", data="", raw=b"")

    @property
    def input_hook(self) -> Callable[[], int] | None:
        """Mock input_hook."""
        return None

    async def repaint(self) -> None:
        """Mock repaint."""
        self.record.append(("action", "repaint"))
