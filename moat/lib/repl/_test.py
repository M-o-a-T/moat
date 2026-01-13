"""Testing utilities for moat.lib.repl."""

from __future__ import annotations

import anyio

from moat.lib.stream import TermBuf

from .fancy_termios import TermState

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Buffer
    from collections.abc import Set as AbstractSet


class MockTerm(TermBuf):
    """
    Mock terminal for testing. Records actions and provides scripted input.

    User actions can be:
        float - delay in seconds before next action
        bytes - mock input to be returned by rd()

    Recorded actions include:
        ("wr", bytes) - data written via wr()
        ("rd", bytes) - bytes read via rd()
        ("set", "raw") - and similar operations

    Instance attributes:
        output_buffer(bytes): accumulated "wr()" data
        record(list[tuple]): Actions; first item is a string
    """

    def __init__(
        self,
        cfg: dict | None = None,
        user_actions: list[float | bytes] | None = None,
    ):
        super().__init__(cfg)
        self.user_actions = list(user_actions) if user_actions else []
        self.record: list[tuple[str, object]] = []
        self.input_buffer = b""
        self.output_buffer = b""
        self._height = 25
        self._width = 80

    async def stream(self):
        return 42

    async def rd(self, buf: Buffer) -> int:
        """Copy up to len(buf) bytes from mock input into buf."""
        # Process user actions until we have input
        while not self.input_buffer and self.user_actions:
            action = self.user_actions.pop(0)
            if isinstance(action, float):
                await anyio.sleep(action)
            elif isinstance(action, bytes):
                self.input_buffer += action

        # Return available data
        buf_mv = memoryview(buf).cast("B")
        n = min(len(buf_mv), len(self.input_buffer))
        if not n:
            self.record.append(("rd", None))
            raise EOFError
        buf_mv[:n] = self.input_buffer[:n]
        self.input_buffer = self.input_buffer[n:]

        self.record.append(("rd", bytes(buf_mv[:n])))
        return n

    async def wr(self, data: Buffer) -> int:
        """Write data to mock output."""
        data_bytes = bytes(data) if not isinstance(data, bytes) else data
        self.record.append(("wr", data_bytes))
        self.output_buffer += data_bytes
        return len(data_bytes)

    async def set_raw(self) -> None:
        """switch to raw mode"""
        self.record.append(("switch", "raw"))

    async def set_orig(self) -> None:
        """switch to previous mode"""
        self.record.append(("switch", "orig"))

    async def tget(self) -> TermState:
        """return current terminfo"""
        self.record.append(("get_ts", None))
        return TermState([0] * 6 + [[b"\0"] * 30])

    async def tset(self, state: TermState, ignore: AbstractSet[int] = frozenset()) -> bool:
        """Set terminfo.

        Args:
            state: Terminal state.
            ignore: errno values to retirn False on.
                (Anything else raises an exception.)

        """
        ignore  # noqa:B018
        self.record.append(("set_ts", state))
        return True

    async def forget_input(self):
        "Delete pending input"
        self.record.append(("forget", "input"))
        raise NotImplementedError

    async def size(self) -> tuple[int, int]:
        "Return terminal height/width tuple"
        self.record.append(("get", "size"))
        return self._height, self._width

    async def rdp(self) -> bytearray:
        """read pending data, without blocking"""
        self.record.append(("read", "pending"))
        return bytearray()
