#   Copyright 2000-2010 Michael Hudson-Doyle <micahel@gmail.com>  # noqa: D100
#                       Antonio Cuni
#                       Armin Rigo
#
#                        All Rights Reserved
#
#
# Permission to use, copy, modify, and distribute this software and
# its documentation for any purpose is hereby granted without fee,
# provided that the above copyright notice appear in all copies and
# that both that copyright notice and this permission notice appear in
# supporting documentation.
#
# THE AUTHOR MICHAEL HUDSON DISCLAIMS ALL WARRANTIES WITH REGARD TO
# THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS, IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL,
# INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER
# RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF
# CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN
# CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

from __future__ import annotations

import anyio
import anyio.abc
import errno
import os
import platform
import re
import select
import signal
import termios
from contextlib import asynccontextmanager

from . import terminfo
from .console import Console, Event
from .trace import trace
from .unix_eventqueue import EventQueue
from .utils import wlen

from typing import TYPE_CHECKING

# types
if TYPE_CHECKING:
    from moat.lib.stream import TermBuf

    from collections.abc import Buffer
    from typing import Literal, cast, overload
else:
    overload = lambda func: None  # noqa: ARG005, E731
    cast = lambda typ, val: val  # noqa: ARG005, E731

# declare posix optional to allow None assignment on other platforms
try:
    import posix  # type: ignore[import-not-found]
except ImportError:
    posix = None  # type: ignore[assignment]

__all__ = ["UnixConsole"]


class InvalidTerminal(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(errno.EIO, message)


_error = (termios.error, InvalidTerminal)
_error_codes_to_ignore = frozenset([errno.EIO, errno.ENXIO, errno.EPERM])

SIGWINCH_EVENT = "repaint"

delayprog = re.compile(b"\\$<([0-9]+)((?:/|\\*){0,2})>")

try:
    poll: type[select.poll] = select.poll
except AttributeError:
    # this is exactly the minimum necessary to support what we
    # do with poll objects
    class MinimalPoll:
        def __init__(self):
            pass

        def register(self, fd, flag):  # noqa: ARG002
            self.fd = fd

        # note: The 'timeout' argument is received as *milliseconds*
        def poll(self, timeout: float | None = None) -> list[int]:
            if timeout is None:
                r, w, e = select.select([self.fd], [], [])
            else:
                r, w, e = select.select([self.fd], [], [], timeout / 1000)  # noqa: RUF059
            return r

    poll = MinimalPoll  # type: ignore[assignment]


class UnixConsole(Console, anyio.AsyncContextManagerMixin):  # noqa: D101
    __read_task: anyio.abc.CancelScope | None = None
    __read_task_end: anyio.Event | None = None

    def __init__(
        self,
        stream: TermBuf | None = None,
        term: str = "",
        encoding: str = "",
    ):
        """
        Initialize the UnixConsole.

        Parameters:
        - f_in (int or file-like object): Input file descriptor or object.
        - f_out (int or file-like object): Output file descriptor or object.
        - term (str): Terminal name.
        - encoding (str): Encoding to use for I/O operations.
        """
        super().__init__(encoding)
        self._wrl = anyio.Lock()

        self.input_buffer = b""
        self.input_buffer_pos = 0

        if stream is None:
            from moat.lib.stream import FilenoTerm  # noqa:PLC0415

            self.__io = FilenoTerm({}, 0, 1)
        else:
            self.__io = stream

        self.is_apple_terminal = (
            platform.system() == "Darwin" and os.getenv("TERM_PROGRAM") == "Apple_Terminal"
        )
        self.term = term

    @asynccontextmanager
    async def __asynccontextmanager__(self):
        term = self.term
        self.terminfo = terminfo.TermInfo(term or os.environ.get("TERM", "VT100"))
        try:
            current_term = await self.__io.tget()
            await self.__io.tset(current_term)
        except _error as e:
            raise RuntimeError(f"termios failure ({e.args[1]})") from e

        @overload
        def _my_getstr(cap: str, optional: Literal[False] = False) -> bytes: ...

        @overload
        def _my_getstr(cap: str, optional: bool) -> bytes | None: ...

        def _my_getstr(cap: str, optional: bool = False) -> bytes | None:
            r = self.terminfo.get(cap)
            if not optional and r is None:
                raise InvalidTerminal(f"terminal doesn't have the required {cap} capability")
            return r

        self._bel = _my_getstr("bel")
        self._civis = _my_getstr("civis", optional=True)
        self._clear = _my_getstr("clear")
        self._cnorm = _my_getstr("cnorm", optional=True)
        self._cub = _my_getstr("cub", optional=True)
        self._cub1 = _my_getstr("cub1", optional=True)
        self._cud = _my_getstr("cud", optional=True)
        self._cud1 = _my_getstr("cud1", optional=True)
        self._cuf = _my_getstr("cuf", optional=True)
        self._cuf1 = _my_getstr("cuf1", optional=True)
        self._cup = _my_getstr("cup")
        self._cuu = _my_getstr("cuu", optional=True)
        self._cuu1 = _my_getstr("cuu1", optional=True)
        self._dch1 = _my_getstr("dch1", optional=True)
        self._dch = _my_getstr("dch", optional=True)
        self._el = _my_getstr("el")
        self._hpa = _my_getstr("hpa", optional=True)
        self._ich = _my_getstr("ich", optional=True)
        self._ich1 = _my_getstr("ich1", optional=True)
        self._ind = _my_getstr("ind", optional=True)
        self._pad = _my_getstr("pad", optional=True)
        self._ri = _my_getstr("ri", optional=True)
        self._rmkx = _my_getstr("rmkx", optional=True)
        self._smkx = _my_getstr("smkx", optional=True)

        self.__setup_movement()

        backspace = (await self.__io.tget()).cc[termios.VERASE]
        self.event_queue = EventQueue(self.encoding, self.terminfo, backspace=backspace)
        self.cursor_visible = 1

        self.screen = []
        self._height, self._width = await self.getheightwidth()

        self.posxy = 0, 0
        self.__gone_tall = 0
        self.__move = self.__move_short
        self.__offset = 0

        async with (
            self.__io,
            anyio.create_task_group() as tg,
        ):

            @tg.start_soon
            async def _winch():
                with anyio.open_signal_receiver(signal.SIGWINCH) as wch:
                    async for _sig in wch:
                        await self.__sigwinch()

            @tg.start_soon
            async def _sigcont():
                with anyio.open_signal_receiver(signal.SIGCONT) as wch:
                    async for _sig in wch:
                        await self.__sigcont()

            self.__tg = tg
            try:
                yield self
            finally:
                tg.cancel_scope.cancel()

    async def _reader(self, task_status=anyio.TASK_STATUS_IGNORED):
        if self.__read_task_end is not None:
            raise RuntimeError("Started twice")
        self.__read_task_end = anyio.Event()
        try:
            with anyio.CancelScope() as sc:
                task_status.started(sc)
                while True:
                    try:
                        self.push_char(await self.__read(1))
                    except EOFError:
                        break
        finally:
            self.__read_task_end.set()

    async def __sigcont(self):
        await self.restore()
        await self.prepare()

    async def __read(self, n: int) -> bytes:
        buf = bytearray(n)
        n = await self.__io.rd(buf)
        buf[n:] = b""
        return bytes(buf)

    async def rd(self, buf: Buffer) -> int:
        """Read up to len(buf) bytes directly from the underlying terminal."""
        return await self.__io.rd(buf)

    async def wr(self, data: Buffer) -> int:
        """Write data directly to the underlying terminal."""
        async with self._wrl:
            return await self.__io.wr(data)

    def change_encoding(self, encoding: str) -> None:
        """
        Change the encoding used for I/O operations.

        Parameters:
        - encoding (str): New encoding to use.
        """
        self.encoding = encoding

    async def refresh(self, screen: list[str], xy: tuple[int, int]) -> None:
        """
        Refresh the console screen.

        Parameters:
        - screen (list): List of strings representing the screen contents.
        - xy (tuple): Cursor position (x, y) on the screen.
        """
        cx, cy = xy
        if not self.__gone_tall:
            while len(self.screen) < min(len(screen), self._height):
                self.__hide_cursor()
                self.__move(0, len(self.screen) - 1)
                self.__write("\n")
                self.posxy = 0, len(self.screen)
                self.screen.append("")
        else:
            while len(self.screen) < len(screen):
                self.screen.append("")

        if len(screen) > self._height:
            self.__gone_tall = 1
            self.__move = self.__move_tall

        px, py = self.posxy  # noqa: RUF059
        old_offset = offset = self.__offset
        height = self._height

        # we make sure the cursor is on the screen, and that we're
        # using all of the screen if we can
        if cy < offset:
            offset = cy
        elif cy >= offset + height:
            offset = cy - height + 1
        elif offset > 0 and len(screen) < offset + height:
            offset = max(len(screen) - height, 0)
            screen.append("")

        oldscr = self.screen[old_offset : old_offset + height]
        newscr = screen[offset : offset + height]

        # use hardware scrolling if we have it.
        if old_offset > offset and self._ri:
            self.__hide_cursor()
            self.__write_code(self._cup, 0, 0)
            self.posxy = 0, old_offset
            for _i in range(old_offset - offset):
                self.__write_code(self._ri)
                oldscr.pop(-1)
                oldscr.insert(0, "")
        elif old_offset < offset and self._ind:
            self.__hide_cursor()
            self.__write_code(self._cup, self._height - 1, 0)
            self.posxy = 0, old_offset + self._height - 1
            for _i in range(offset - old_offset):
                self.__write_code(self._ind)
                oldscr.pop(0)
                oldscr.append("")

        self.__offset = offset

        for (
            y,
            oldline,
            newline,
        ) in zip(range(offset, offset + height), oldscr, newscr, strict=False):
            if oldline != newline:
                self.__write_changed_line(y, oldline, newline, px)

        y = len(newscr)
        while y < len(oldscr):
            self.__hide_cursor()
            self.__move(0, y)
            self.posxy = 0, y
            self.__write_code(self._el)
            y += 1

        self.__show_cursor()

        self.screen = screen.copy()
        await self.move_cursor(cx, cy)
        await self.flushoutput()

    async def move_cursor(self, x, y):
        """
        Move the cursor to the specified position on the screen.

        Parameters:
        - x (int): X coordinate.
        - y (int): Y coordinate.
        """
        if y < self.__offset or y >= self.__offset + self._height:
            self.event_queue.insert(Event("scroll", None))
        else:
            self.__move(x, y)
            self.posxy = x, y

    async def prepare(self, reader: bool = True):
        """
        Prepare the console for input/output operations.
        """

        self.__buffer = []
        self.screen = []
        self.posxy = 0, 0
        self.__gone_tall = 0
        self.__move = self.__move_short
        self.__offset = 0

        self._height, self._width = await self.getheightwidth()

        if self.__read_task_end is not None:
            await self.restore()
            raise RuntimeError("Already prepared")
        if reader:
            self.__read_task = await self.__tg.start(self._reader)

        await self.__io.set_raw()

        # In macOS terminal we need to deactivate line wrap via ANSI escape code
        if self.is_apple_terminal:
            async with self._wrl:
                await self.__io.wr(b"\033[?7l")

        self.__maybe_write_code(self._smkx)
        await self.__enable_bracketed_paste()

    async def restore(self):
        """
        Restore the console to the default state
        """
        if self.__read_task_end is not None:
            # cannot be None if _r_t_e is not None
            self.__read_task.cancel()  # type:ignore[possibly-missing-attribute]
            await self.__read_task_end.wait()
            self.__read_task = None
            self.__read_task_end = None
        await self.__disable_bracketed_paste()
        self.__maybe_write_code(self._rmkx)
        await self.flushoutput()
        await self.__io.set_orig()

        if self.is_apple_terminal:
            async with self._wrl:
                await self.__io.wr(b"\033[?7h")

    def push_char(self, char: int | bytes) -> None:
        """
        Push a character to the console event queue.
        """
        trace("push char {char!r}", char=char)
        self.event_queue.push(char)

    async def get_event(self) -> Event:
        """
        Get an event from the console event queue.

        Returns:
        - Event: Event object from the event queue.
        """
        return await self.event_queue.get()

    async def set_cursor_vis(self, visible):
        """
        Set the visibility of the cursor.

        Parameters:
        - visible (bool): Visibility flag.
        """
        if visible:
            self.__show_cursor()
        else:
            self.__hide_cursor()

    async def getheightwidth(self) -> tuple[int, int]:
        """
        Get the height and width of the console.

        Returns: Height and width of the console.
        """
        try:
            return await self.__io.size()
        except Exception:
            try:
                return int(os.environ["LINES"]), int(os.environ["COLUMNS"])
            except (KeyError, TypeError, ValueError):
                return 25, 80

    async def forgetinput(self):
        """
        Discard any pending input on the console.
        """
        await self.__io.forget_input()

    async def flushoutput(self):
        """
        Flush the output buffer.
        """
        buf = []

        async with self._wrl:

            async def _flush():
                nonlocal buf
                if buf:
                    await self.__io.wr(b"".join(buf))
                    buf = []

            for text, iscode in self.__buffer:
                if iscode:
                    await _flush()
                    await self.__tputs(text)
                else:
                    buf.append(text.encode(self.encoding, "replace"))
            await _flush()

            del self.__buffer[:]

    async def finish(self):
        """
        Finish console operations and flush the output buffer.
        """
        y = len(self.screen) - 1
        while y >= 0 and not self.screen[y]:
            y -= 1
        self.__move(0, min(y, self._height + self.__offset - 1))
        self.__write("\n")
        await self.flushoutput()

    async def beep(self):
        """
        Emit a beep sound.
        """
        self.__maybe_write_code(self._bel)
        await self.flushoutput()

    async def getpending(self):
        """
        Get pending events from the console event queue.

        Returns:
        - Event: Pending event from the event queue.
        """
        e = Event("key", "", b"")

        while not self.event_queue.empty():
            e2 = await self.event_queue.get()
            if e.evt != "key":
                raise ValueError(repr(e))
            e.data += e2.data
            e.raw += e.raw

        raw = await self.__io.rdp()
        data = str(raw, self.encoding, "replace")
        e.data += data
        e.raw += raw
        return e

    async def clear(self):
        """
        Clear the console screen.
        """
        self.__write_code(self._clear)
        self.__gone_tall = 1
        self.__move = self.__move_tall
        self.posxy = 0, 0
        self.screen = []

    @property
    def input_hook(self):  # noqa: D102
        if posix is not None and posix._is_inputhook_installed():  # noqa: SLF001  # type: ignore[attr-defined]
            return posix._inputhook  # noqa: SLF001  # type: ignore[attr-defined]

    async def __enable_bracketed_paste(self) -> None:
        async with self._wrl:
            await self.__io.wr(b"\x1b[?2004h")

    async def __disable_bracketed_paste(self) -> None:
        async with self._wrl:
            await self.__io.wr(b"\x1b[?2004l")

    def __setup_movement(self):
        """
        Set up the movement functions based on the terminal capabilities.
        """
        if False:  # hpa don't work in windows telnet :-(
            self.__move_x = self.__move_x_hpa
        elif self._cub and self._cuf:
            self.__move_x = self.__move_x_cub_cuf
        elif self._cub1 and self._cuf1:
            self.__move_x = self.__move_x_cub1_cuf1
        else:
            raise RuntimeError("insufficient terminal (horizontal)")

        if self._cuu and self._cud:
            self.__move_y = self.__move_y_cuu_cud
        elif self._cuu1 and self._cud1:
            self.__move_y = self.__move_y_cuu1_cud1
        else:
            raise RuntimeError("insufficient terminal (vertical)")

        if self._dch1:
            self.dch1 = self._dch1
        elif self._dch:
            self.dch1 = terminfo.tparm(self._dch, 1)
        else:
            self.dch1 = None

        if self._ich1:
            self.ich1 = self._ich1
        elif self._ich:
            self.ich1 = terminfo.tparm(self._ich, 1)
        else:
            self.ich1 = None

        self.__move = self.__move_short

    def __write_changed_line(self, y, oldline, newline, px_coord):
        # this is frustrating; there's no reason to test (say)
        # self.dch1 inside the loop -- but alternative ways of
        # structuring this function are equally painful (I'm trying to
        # avoid writing code generators these days...)
        minlen = min(wlen(oldline), wlen(newline))
        x_pos = 0
        x_coord = 0

        px_pos = 0
        j = 0
        for c in oldline:
            if j >= px_coord:
                break
            j += wlen(c)
            px_pos += 1

        # reuse the oldline as much as possible, but stop as soon as we
        # encounter an ESCAPE, because it might be the start of an escape
        # sequence
        while x_coord < minlen and oldline[x_pos] == newline[x_pos] and newline[x_pos] != "\x1b":
            x_coord += wlen(newline[x_pos])
            x_pos += 1

        # if we need to insert a single character right after the first detected change
        if oldline[x_pos:] == newline[x_pos + 1 :] and self.ich1:
            if (
                y == self.posxy[1]
                and x_coord > self.posxy[0]
                and oldline[px_pos:x_pos] == newline[px_pos + 1 : x_pos + 1]
            ):
                x_pos = px_pos
                x_coord = px_coord
            character_width = wlen(newline[x_pos])
            self.__move(x_coord, y)
            self.__write_code(self.ich1)
            self.__write(newline[x_pos])
            self.posxy = x_coord + character_width, y

        # if it's a single character change in the middle of the line
        elif (
            x_coord < minlen
            and oldline[x_pos + 1 :] == newline[x_pos + 1 :]
            and wlen(oldline[x_pos]) == wlen(newline[x_pos])
        ):
            character_width = wlen(newline[x_pos])
            self.__move(x_coord, y)
            self.__write(newline[x_pos])
            self.posxy = x_coord + character_width, y

        # if this is the last character to fit in the line and we edit in the middle of the line
        elif (
            self.dch1
            and self.ich1
            and wlen(newline) == self._width
            and x_coord < wlen(newline) - 2
            and newline[x_pos + 1 : -1] == oldline[x_pos:-2]
        ):
            self.__hide_cursor()
            self.__move(self._width - 2, y)
            self.posxy = self._width - 2, y
            self.__write_code(self.dch1)

            character_width = wlen(newline[x_pos])
            self.__move(x_coord, y)
            self.__write_code(self.ich1)
            self.__write(newline[x_pos])
            self.posxy = character_width + 1, y

        else:
            self.__hide_cursor()
            self.__move(x_coord, y)
            if wlen(oldline) > wlen(newline):
                self.__write_code(self._el)
            self.__write(newline[x_pos:])
            self.posxy = wlen(newline), y

        if "\x1b" in newline:
            # ANSI escape characters are present, so we can't assume
            # anything about the position of the cursor.  Moving the cursor
            # to the left margin should work to get to a known position.
            self.move_cursor(0, y)

    def __write(self, text):
        self.__buffer.append((text, 0))

    def __write_code(self, fmt, *args):
        self.__buffer.append((terminfo.tparm(fmt, *args), 1))

    def __maybe_write_code(self, fmt, *args):
        if fmt:
            self.__write_code(fmt, *args)

    def __move_y_cuu1_cud1(self, y):
        assert self._cud1 is not None
        assert self._cuu1 is not None
        dy = y - self.posxy[1]
        if dy > 0:
            self.__write_code(dy * self._cud1)
        elif dy < 0:
            self.__write_code((-dy) * self._cuu1)

    def __move_y_cuu_cud(self, y):
        dy = y - self.posxy[1]
        if dy > 0:
            self.__write_code(self._cud, dy)
        elif dy < 0:
            self.__write_code(self._cuu, -dy)

    def __move_x_hpa(self, x: int) -> None:
        if x != self.posxy[0]:
            self.__write_code(self._hpa, x)

    def __move_x_cub1_cuf1(self, x: int) -> None:
        assert self._cuf1 is not None
        assert self._cub1 is not None
        dx = x - self.posxy[0]
        if dx > 0:
            self.__write_code(self._cuf1 * dx)
        elif dx < 0:
            self.__write_code(self._cub1 * (-dx))

    def __move_x_cub_cuf(self, x: int) -> None:
        dx = x - self.posxy[0]
        if dx > 0:
            self.__write_code(self._cuf, dx)
        elif dx < 0:
            self.__write_code(self._cub, -dx)

    def __move_short(self, x, y):
        self.__move_x(x)
        self.__move_y(y)

    def __move_tall(self, x, y):
        assert 0 <= y - self.__offset < self._height, y - self.__offset
        self.__write_code(self._cup, y - self.__offset, x)

    async def __sigwinch(self):
        self._height, self._width = await self.getheightwidth()
        self.event_queue.insert(Event("resize", None))

    def __hide_cursor(self):
        if self.cursor_visible:
            self.__maybe_write_code(self._civis)
            self.cursor_visible = 0

    def __show_cursor(self):
        if not self.cursor_visible:
            self.__maybe_write_code(self._cnorm)
            self.cursor_visible = 1

    async def repaint(self):  # noqa: D102
        if not self.__gone_tall:
            self.posxy = 0, self.posxy[1]
            self.__write("\r")
            ns = len(self.screen) * ["\000" * self._width]
            self.screen = ns
        else:
            self.posxy = 0, self.__offset
            self.__move(0, self.__offset)
            ns = self._height * ["\000" * self._width]
            self.screen = ns

    async def __tputs(self, fmt, prog=delayprog):
        """A Python implementation of the curses tputs function; the
        curses one can't really be wrapped in a sane manner.
        """
        while True:
            m = prog.search(fmt)
            if not m:
                await self.__io.wr(fmt)
                break
            x, y = m.span()
            await self.__io.wr(fmt[:x])
            fmt = fmt[y:]
            delay = int(m.group(1))
            if b"*" in m.group(2):
                delay *= self._height
            await anyio.sleep(float(delay) / 1000.0)
