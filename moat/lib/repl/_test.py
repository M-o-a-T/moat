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
        ("rd", int) - number of bytes requested via rd()
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
        self.recorded_actions: list[tuple[str, object]] = []
        self.input_buffer = b""
        self.output_buffer = b""
        self._height = 25
        self._width = 80

    @asynccontextmanager
    async def __asynccontextmanager__(self):
        """Async context manager for console lifecycle."""
        self.recorded_actions.append(("action", "enter"))
        try:
            yield self
        finally:
            self.recorded_actions.append(("action", "exit"))

    async def rd(self, n: int) -> bytes:
        """Read up to n bytes from mock input."""
        self.recorded_actions.append(("rd", n))

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
        return result

    async def wr(self, data: bytes) -> None:
        """Write data to mock output."""
        self.recorded_actions.append(("wr", data))
        self.output_buffer += data

    async def prepare(self) -> None:
        """Mock prepare."""
        self.recorded_actions.append(("action", "prepare"))
        self.screen = []
        self.height, self.width = self._height, self._width

    async def restore(self) -> None:
        """Mock restore."""
        self.recorded_actions.append(("action", "restore"))

    async def refresh(self, screen: list[str], xy: tuple[int, int]) -> None:  # noqa: ARG002
        """Mock refresh."""
        self.recorded_actions.append(("action", "refresh"))

    async def move_cursor(self, x: int, y: int) -> None:
        """Mock move_cursor."""
        self.recorded_actions.append(("action", f"move_cursor({x},{y})"))

    async def set_cursor_vis(self, visible: bool) -> None:
        """Mock set_cursor_vis."""
        self.recorded_actions.append(("action", f"set_cursor_vis({visible})"))

    async def getheightwidth(self) -> tuple[int, int]:
        """Return mock terminal size."""
        self.recorded_actions.append(("action", "getheightwidth"))
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
        self.recorded_actions.append(("action", "beep"))

    async def clear(self) -> None:
        """Mock clear."""
        self.recorded_actions.append(("action", "clear"))

    async def finish(self) -> None:
        """Mock finish."""
        self.recorded_actions.append(("action", "finish"))

    async def flushoutput(self) -> None:
        """Mock flushoutput."""
        self.recorded_actions.append(("action", "flushoutput"))

    async def forgetinput(self) -> None:
        """Mock forgetinput."""
        self.recorded_actions.append(("action", "forgetinput"))

    async def getpending(self) -> Event:
        """Mock getpending."""
        self.recorded_actions.append(("action", "getpending"))
        return Event(evt="", data="", raw=b"")

    @property
    def input_hook(self) -> Callable[[], int] | None:
        """Mock input_hook."""
        return None

    async def repaint(self) -> None:
        """Mock repaint."""
        self.recorded_actions.append(("action", "repaint"))
