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

import _colorize  # type: ignore[import-not-found]
from attrs import define, field

TYPE_CHECKING = False

if TYPE_CHECKING:
    from collections.abc import Buffer, Callable

__all__ = ["Console", "Event", "InteractiveColoredConsole", "Readline"]


@define
class Event:  # noqa: D101
    evt: str
    data: str
    raw: bytes = b""

    def __init__(self, evt: str, data: str | None = None, raw: bytes = b""):
        self.evt = evt
        self.data = data or ""
        self.raw = raw


try:
    from moat.lib.proxy import as_proxy
except ImportError:
    pass
else:
    as_proxy("_replEvt", Event)


@define
class Console(ABC):  # noqa: D101
    posxy: tuple[int, int]
    screen: list[str] = field(factory=list)
    height: int = 25
    width: int = 80

    def __init__(
        self,
        encoding: str = "",
    ):
        self.encoding = encoding or sys.getdefaultencoding()

    @abstractmethod
    async def refresh(self, screen: list[str], xy: tuple[int, int]) -> None: ...  # noqa: D102

    @abstractmethod
    async def prepare(self) -> None: ...  # noqa: D102

    @abstractmethod
    async def restore(self) -> None: ...  # noqa: D102

    @abstractmethod
    async def move_cursor(self, x: int, y: int) -> None: ...  # noqa: D102

    @abstractmethod
    async def set_cursor_vis(self, visible: bool) -> None: ...  # noqa: D102

    @abstractmethod
    async def getheightwidth(self) -> tuple[int, int]:
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
    async def beep(self) -> None: ...  # noqa: D102

    @abstractmethod
    async def clear(self) -> None:
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
    async def forgetinput(self) -> None:
        """Forget all pending, but not yet processed input."""
        ...

    @abstractmethod
    async def getpending(self) -> Event:
        """Return the characters that have been typed but not yet
        processed."""
        ...

    @property
    @abstractmethod
    def input_hook(self) -> Callable[[], int] | None:
        """Returns the current input hook."""
        ...

    @abstractmethod
    async def repaint(self) -> None: ...  # noqa: D102

    @abstractmethod
    async def rd(self, buf: Buffer) -> int:
        """Read up to n bytes from the underlying terminal."""
        ...

    @abstractmethod
    async def wr(self, data: Buffer) -> int:
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
        super().__init__(locals=locals, filename=filename, local_exit=local_exit)  # type: ignore[call-arg]
        self.can_colorize = _colorize.can_colorize()

    def showsyntaxerror(self, filename=None, **kwargs):  # noqa: D102
        super().showsyntaxerror(filename=filename, **kwargs)

    def _excepthook(self, typ, value, tb):
        import traceback  # noqa: PLC0415

        lines = traceback.format_exception(  # type: ignore[call-overload,attr-defined]
            typ,
            value,
            tb,
            colorize=self.can_colorize,
            limit=traceback.BUILTIN_EXCEPTION_LIMIT,  # type: ignore[attr-defined]
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
            tree = self.compile.compiler(  # type: ignore[call-arg,call-overload,misc,arg-type]
                source,
                filename,
                "exec",
                ast.PyCF_ONLY_AST,  # type: ignore[misc]
                incomplete_input=False,  # type: ignore[misc]
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
        if tree.body:  # type: ignore[attr-defined]
            *_, last_stmt = tree.body  # type: ignore[attr-defined]
        for stmt in tree.body:  # type: ignore[attr-defined]
            wrapper = ast.Interactive if stmt is last_stmt else ast.Module
            the_symbol = symbol if stmt is last_stmt else "exec"
            item = wrapper([stmt])
            try:
                code = self.compile.compiler(item, filename, the_symbol)  # type: ignore[arg-type]
                linecache._register_code(code, source, filename)  # noqa: SLF001  # type: ignore[attr-defined]
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


class Readline:
    """
    Async iterator interface for reading lines from a console.

    Usage:
        # Single-line input
        async with Readline(console, prompt=">>> ") as lines:
            async for line in lines:
                process(line)

        # Multi-line input
        async with Readline(console, prompt=">>> ", more_lines=check_continuation) as lines:
            async for line in lines:
                process(line)
    """

    def __init__(
        self,
        console: Console,
        prompt: str = ">>> ",
        more_lines: Callable[[str], bool] | None = None,
        ps1: str | None = None,
        ps2: str | None = None,
        ps3: str | None = None,
        ps4: str | None = None,
    ):
        """Initialize with a console and optional prompt/multiline settings."""
        self.console = console
        self.prompt = prompt
        self.more_lines = more_lines
        self.ps1 = ps1 or prompt
        self.ps2 = ps2 or prompt
        self.ps3 = ps3 or "|.. "
        self.ps4 = ps4 or R"\__ "
        self.reader = None

    async def __aenter__(self):
        """Enter async context and create reader."""
        from .reader import Reader  # noqa: PLC0415

        reader = Reader(console=self.console)
        reader.ps1 = self.ps1
        reader.ps2 = self.ps2
        reader.ps3 = self.ps3
        reader.ps4 = self.ps4
        reader.more_lines = self.more_lines

        # Enter the reader's context to do prepare() once
        await reader.__aenter__()
        self.reader = reader

        return self

    async def __aexit__(self, *exc):
        """Exit async context and clean up."""
        if self.reader is not None:
            # Exit the reader's context to do restore() once
            try:
                await self.reader.__aexit__(*exc)
            finally:
                self.reader = None

    def __aiter__(self):
        """Return self as async iterator."""
        return self

    async def __anext__(self) -> str:
        """Read and return the next line."""
        if self.reader is None:
            raise StopAsyncIteration
        try:
            # Reset state for next line
            self.reader.finished = False
            self.reader.buffer.clear()
            self.reader.pos = 0
            line = await self.reader.readline()
            return line
        except EOFError:
            raise StopAsyncIteration from None
