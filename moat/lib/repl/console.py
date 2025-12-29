#   Copyright 2000-2004 Michael Hudson-Doyle <micahel@gmail.com>  # noqa: D100
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

import ast
import code
import linecache
import os.path
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import _colorize

from moat.lib.rpc import MsgHandler

TYPE_CHECKING = False

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import IO


@dataclass
class Event:  # noqa: D101
    evt: str
    data: str
    raw: bytes = b""


@dataclass
class Console(ABC):  # noqa: D101
    posxy: tuple[int, int]
    screen: list[str] = field(default_factory=list)
    height: int = 25
    width: int = 80

    def __init__(
        self,
        f_in: IO[bytes] | int = 0,
        f_out: IO[bytes] | int = 1,
        term: str = "",  # noqa: ARG002
        encoding: str = "",
    ):
        self.encoding = encoding or sys.getdefaultencoding()

        if isinstance(f_in, int):
            self.input_fd = f_in
        else:
            self.input_fd = f_in.fileno()

        if isinstance(f_out, int):
            self.output_fd = f_out
        else:
            self.output_fd = f_out.fileno()

    @abstractmethod
    async def refresh(self, screen: list[str], xy: tuple[int, int]) -> None: ...  # noqa: D102

    @abstractmethod
    async def prepare(self) -> None: ...  # noqa: D102

    @abstractmethod
    async def restore(self) -> None: ...  # noqa: D102

    @abstractmethod
    def move_cursor(self, x: int, y: int) -> None: ...  # noqa: D102

    @abstractmethod
    def set_cursor_vis(self, visible: bool) -> None: ...  # noqa: D102

    @abstractmethod
    def getheightwidth(self) -> tuple[int, int]:
        """Return (height, width) where height and width are the height
        and width of the terminal window in characters."""
        ...

    @abstractmethod
    async def get_event(self) -> Event:
        """
        Return the next Event instance.
        """
        ...

    @abstractmethod
    def push_char(self, char: int | bytes) -> None:
        """
        Push a character to the console event queue.
        """
        ...

    @abstractmethod
    def beep(self) -> None: ...  # noqa: D102

    @abstractmethod
    def clear(self) -> None:
        """Wipe the screen"""
        ...

    @abstractmethod
    async def finish(self) -> None:
        """Move the cursor to the end of the display and otherwise get
        ready for end.  XXX could be merged with restore?  Hmm."""
        ...

    @abstractmethod
    async def flushoutput(self) -> None:
        """Flush all output to the screen (assuming there's some
        buffering going on somewhere)."""
        ...

    @abstractmethod
    def forgetinput(self) -> None:
        """Forget all pending, but not yet processed input."""
        ...

    @abstractmethod
    def getpending(self) -> Event:
        """Return the characters that have been typed but not yet
        processed."""
        ...

    @property
    @abstractmethod
    def input_hook(self) -> Callable[[], int] | None:
        """Returns the current input hook."""
        ...

    @abstractmethod
    def repaint(self) -> None: ...  # noqa: D102

    @abstractmethod
    async def rd(self, n: int) -> bytes:
        """Read up to n bytes from the underlying terminal."""
        ...

    @abstractmethod
    async def wr(self, data: bytes) -> None:
        """Write data to the underlying terminal."""
        ...


class InteractiveColoredConsole(code.InteractiveConsole):  # noqa: D101
    STATEMENT_FAILED = object()

    def __init__(
        self,
        locals: dict[str, object] | None = None,  # noqa: A002
        filename: str = "<console>",
        *,
        local_exit: bool = False,
    ) -> None:
        super().__init__(locals=locals, filename=filename, local_exit=local_exit)
        self.can_colorize = _colorize.can_colorize()

    def showsyntaxerror(self, filename=None, **kwargs):  # noqa: D102
        super().showsyntaxerror(filename=filename, **kwargs)

    def _excepthook(self, typ, value, tb):
        import traceback  # noqa: PLC0415

        lines = traceback.format_exception(
            typ, value, tb, colorize=self.can_colorize, limit=traceback.BUILTIN_EXCEPTION_LIMIT
        )
        self.write("".join(lines))

    def runcode(self, code):  # noqa: D102
        try:
            exec(code, self.locals)  # noqa: S102
        except SystemExit:
            raise
        except BaseException:
            self.showtraceback()
            return self.STATEMENT_FAILED
        return None

    def runsource(self, source, filename="<input>", symbol="single"):  # noqa: D102
        try:
            tree = self.compile.compiler(
                source,
                filename,
                "exec",
                ast.PyCF_ONLY_AST,
                incomplete_input=False,
            )
        except SyntaxError as e:
            # If it looks like pip install was entered (a common beginner
            # mistake), provide a hint to use the system command prompt.
            if re.match(r"^\s*(pip3?|py(thon3?)? -m pip) install.*", source):
                e.add_note(
                    "The Python package manager (pip) can only be used"
                    " outside of the Python REPL.\n"
                    "Try the 'pip' command in a separate terminal or"
                    " command prompt."
                )
            self.showsyntaxerror(filename, source=source)
            return False
        except (OverflowError, ValueError):
            self.showsyntaxerror(filename, source=source)
            return False
        if tree.body:
            *_, last_stmt = tree.body
        for stmt in tree.body:
            wrapper = ast.Interactive if stmt is last_stmt else ast.Module
            the_symbol = symbol if stmt is last_stmt else "exec"
            item = wrapper([stmt])
            try:
                code = self.compile.compiler(item, filename, the_symbol)
                linecache._register_code(code, source, filename)  # noqa: SLF001
            except SyntaxError as e:
                if e.args[0] == "'await' outside function":
                    python = os.path.basename(sys.executable)
                    e.add_note(
                        f"Try the asyncio REPL ({python} -m asyncio) to use"
                        f" top-level 'await' and run background asyncio tasks."
                    )
                self.showsyntaxerror(filename, source=source)
                return False
            except (OverflowError, ValueError):
                self.showsyntaxerror(filename, source=source)
                return False

            if code is None:
                return True

            result = self.runcode(code)
            if result is self.STATEMENT_FAILED:
                break
        return False


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


class MoatConsole:
    """
    Client-side console proxy that uses RPC to communicate with a remote MsgConsole.

    Usage:
        ux = UnixConsole()
        tty = MsgConsole(ux)
        snd = MsgSender(tty)
        moat = MoatConsole(snd)
        # Call chain: moat.rd(10) -> snd.rd(n=10) -> tty.cmd_rd(10) -> ux.rd(10)
        data = await moat.rd(10)
    """

    def __init__(self, sender):
        """Initialize with a MsgSender instance."""
        self.sender = sender

    async def rd(self, n: int) -> bytes:
        """Read up to n bytes from the remote console."""
        return await self.sender.rd(n=n)

    async def wr(self, data: bytes) -> None:
        """Write data to the remote console."""
        await self.sender.wr(data=data)


class Readline:
    """
    Async iterator interface for reading lines from a console.

    Usage:
        async with Readline(console, prompt=">>> ") as lines:
            async for line in lines:
                process(line)
    """

    def __init__(self, console: Console, prompt: str = ">>> "):
        """Initialize with a console and optional prompt."""
        self.console = console
        self.prompt = prompt
        self.reader = None

    async def __aenter__(self):
        """Enter async context and create reader."""
        from .reader import Reader  # noqa: PLC0415

        self.reader = Reader(console=self.console)
        self.reader.ps1 = self.prompt
        return self

    async def __aexit__(self, *exc):
        """Exit async context and clean up."""
        self.reader = None
        return False

    def __aiter__(self):
        """Return self as async iterator."""
        return self

    async def __anext__(self) -> str:
        """Read and return the next line."""
        if self.reader is None:
            raise StopAsyncIteration
        try:
            line = await self.reader.readline()
            return line
        except EOFError:
            raise StopAsyncIteration from None
