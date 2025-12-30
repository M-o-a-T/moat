"Stream enhancements for terminals"

from __future__ import annotations

import anyio
import errno
import os
import struct
import termios
from fcntl import ioctl

from moat.lib.repl import tcgetattr, tcsetattr
from moat.lib.stream import BaseBuf

from .anyio import FilenoBuf

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.repl import TermState

    from collections.abc import AbstractSet


__all__ = ["FilenoTerm", "InvalidTerminal"]

TIOCGWINSZ = getattr(termios, "TIOCGWINSZ", None)
FIONREAD = getattr(termios, "FIONREAD", None)


class InvalidTerminal(RuntimeError):
    "Terminal problem exception"

    def __init__(self, message: str) -> None:
        super().__init__(errno.EIO, message)


_error = (termios.error, InvalidTerminal)
_error_codes_to_ignore = frozenset([errno.EIO, errno.ENXIO, errno.EPERM])


class TermBuf(BaseBuf):
    """
    An abstrace `BaseBuf`-derived class, enhanced with terminal access.
    """

    async def set_raw(self) -> None:
        """switch to raw mode"""
        raise NotImplementedError

    async def set_orig(self) -> None:
        """switch to previous mode"""
        raise NotImplementedError

    async def tget(self) -> TermState:
        """return current terminfo"""
        raise NotImplementedError

    async def tset(self, state: TermState, ignore: AbstractSet[int] = frozenset()) -> bool:
        """Set terminfo.

        Args:
            state: Terminal state.
            ignore: errno values to retirn False on.
                (Anything else raises an exception.)

        """
        raise NotImplementedError

    async def forget_input(self):
        "Delete pending input"
        raise NotImplementedError

    async def size(self) -> tuple[int, int]:
        "Return terminal height/width tuple"
        raise NotImplementedError

    async def rdp(self) -> bytearray:
        """read pending data, without blocking"""
        raise NotImplementedError


class FilenoTerm(FilenoBuf, TermBuf):
    """
    A `FilenoBuf`, enhanced with terminal access.

    Used primarily for the REPL.

    Warning: Setting up raw mode etc. is the responsibility of the caller.
    """

    async def setup(self):  # noqa:D102
        await super().setup()

        self.__orig_termstate = await self.tget()
        raw = self.__orig_termstate.copy()
        raw.iflag &= ~(termios.INPCK | termios.ISTRIP | termios.IXON)
        raw.oflag &= ~(termios.OPOST)
        raw.cflag &= ~(termios.CSIZE | termios.PARENB)
        raw.cflag |= termios.CS8
        raw.iflag |= termios.BRKINT
        raw.lflag &= ~(termios.ICANON | termios.ECHO | termios.IEXTEN)
        raw.lflag |= termios.ISIG
        raw.cc[termios.VMIN] = 1
        raw.cc[termios.VTIME] = 0
        self.__raw_termstate = raw

    async def set_raw(self) -> None:
        """switch to raw mode"""
        return await self.tset(self.__raw_termstate)

    async def set_orig(self) -> None:
        """switch to previous mode"""
        return await self.tset(self.__orig_termstate)

    async def tget(self) -> TermState:
        """return current terminfo"""
        return tcgetattr(self.rfd)

    async def tset(self, state: TermState, ignore: AbstractSet[int] = frozenset()) -> bool:
        """Set terminfo.

        Args:
            state: Terminal state.
            ignore: errno values to retirn False on.
                (Anything else raises an exception.)

        """
        try:
            await anyio.to_thread.run_sync(tcsetattr, self.rfd, termios.TCSADRAIN, state)
        except termios.error as te:
            if te.args[0] not in ignore:
                raise
            return False
        else:
            return True

    async def forget_input(self):
        "Delete pending input"
        termios.tcflush(self.rfd, termios.TCIFLUSH)

    async def size(self) -> tuple[int, int]:
        "Return terminal height/width tuple"
        if TIOCGWINSZ:
            try:
                size = ioctl(self.rfd, TIOCGWINSZ, b"\000" * 8)
            except OSError:
                pass
            else:
                height, width = struct.unpack("hhhh", size)[0:2]
                if height:
                    return height, width
        try:
            return int(os.environ["LINES"]), int(os.environ["COLUMNS"])
        except (KeyError, TypeError, ValueError):
            return 25, 80

    async def rdp(self) -> bytearray:
        """read pending data, without blocking"""
        amount = struct.unpack("i", ioctl(self.rfd, FIONREAD, b"\0\0\0\0"))[0]
        return os.read(self.rfd, amount)
