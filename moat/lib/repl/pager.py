from __future__ import annotations  # noqa: D100

import io
import os
import re
import shlex
import shutil
import sys
from anyio.to_thread import run_sync

from moat.util.exec import CalledProcessError, run

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Protocol

    class Pager(Protocol):
        async def __call__(self, text: str, title: str = "") -> None: ...


__all__ = ["pipe_pager", "plain_pager", "tempfile_pager"]


async def get_pager() -> Pager:
    """Decide what method to use for paging through text."""
    if not hasattr(sys.stdin, "isatty"):
        return plain_pager
    if not hasattr(sys.stdout, "isatty"):
        return plain_pager
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return plain_pager
    if sys.platform == "emscripten":
        return plain_pager
    use_pager = os.environ.get("MANPAGER") or os.environ.get("PAGER")
    if use_pager:
        if sys.platform == "win32":  # pipes completely broken in Windows
            return _make_tempfile(use_pager, plain_text=True)
        elif os.environ.get("TERM") in ("dumb", "emacs"):
            return _make_pipe(use_pager, plain_text=True)
        else:
            return _make_pipe(use_pager, plain_text=False)
    if os.environ.get("TERM") in ("dumb", "emacs"):
        return plain_pager
    if sys.platform == "win32":
        return _make_tempfile("more", plain_text=True)
    for prog in ("pager", "less", "more"):
        if shutil.which(prog) is not None:
            return _make_pipe(prog, plain_text=False)
    return tty_pager


def _make_pipe(cmd: str, *, plain_text: bool) -> Pager:
    """Build a pager that feeds *text* to *cmd* via its standard input."""

    async def pager(text: str, title: str = "") -> None:
        await pipe_pager(plain(text) if plain_text else text, cmd, title)

    return pager


def _make_tempfile(cmd: str, *, plain_text: bool) -> Pager:
    """Build a pager that presents *text* to *cmd* via a temporary file."""

    async def pager(text: str, title: str = "") -> None:  # noqa: ARG001
        await tempfile_pager(plain(text) if plain_text else text, cmd)

    return pager


def escape_stdout(text: str) -> str:
    # Escape non-encodable characters to avoid encoding errors later
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, "backslashreplace").decode(encoding)


def escape_less(s: str) -> str:
    return re.sub(r"([?:.%\\])", r"\\\1", s)


def plain(text: str) -> str:
    """Remove boldface formatting from text."""
    return re.sub(".\b", "", text)


def _tty_pager_sync(text: str, title: str) -> None:  # noqa: ARG001
    """Page through text on a text terminal (blocking)."""
    lines = plain(escape_stdout(text)).split("\n")
    has_tty = False
    try:
        import termios  # noqa: PLC0415
        import tty  # noqa: PLC0415

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        has_tty = True

        def getchar() -> str:
            return sys.stdin.read(1)

    except (ImportError, AttributeError, io.UnsupportedOperation):

        def getchar() -> str:
            return sys.stdin.readline()[:-1][:1]

    try:
        try:
            h = int(os.environ.get("LINES", "0"))
        except ValueError:
            h = 0
        if h <= 1:
            h = 25
        r = inc = h - 1
        sys.stdout.write("\n".join(lines[:inc]) + "\n")
        while lines[r:]:
            sys.stdout.write("-- more --")
            sys.stdout.flush()
            c = getchar()

            if c in ("q", "Q"):
                sys.stdout.write("\r          \r")
                break
            elif c in ("\r", "\n"):
                sys.stdout.write("\r          \r" + lines[r] + "\n")
                r = r + 1
                continue
            if c in ("b", "B", "\x1b"):
                r = r - inc - inc
                if r < 0:
                    r = 0
            sys.stdout.write("\n" + "\n".join(lines[r : r + inc]) + "\n")
            r = r + inc

    finally:
        if has_tty:
            termios.tcsetattr(fd, termios.TCSAFLUSH, old)


async def tty_pager(text: str, title: str = "") -> None:
    """Page through text on a text terminal."""
    await run_sync(_tty_pager_sync, text, title, abandon_on_cancel=True)


async def plain_pager(text: str, title: str = "") -> None:  # noqa: ARG001
    """Simply print unformatted text.  This is the ultimate fallback."""
    sys.stdout.write(plain(escape_stdout(text)))


async def pipe_pager(text: str, cmd: str, title: str = "") -> None:
    """Page through text by feeding it to another program."""
    env = os.environ.copy()
    if title:
        title += " "
    esc_title = escape_less(title)
    prompt_string = (
        f" {esc_title}"
        "?ltline %lt?L/%L."
        ":byte %bB?s/%s."
        "."
        "?e (END):?pB %pB\\%.."
        " (press h for help or q to quit)"
    )
    env["LESS"] = f"-RmPm{prompt_string}$PM{prompt_string}$"
    try:
        await run(
            *shlex.split(cmd),
            input=text,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=env,
        )
    except (ConnectionError, CalledProcessError):
        pass  # the pager quit early or returned nonzero


async def tempfile_pager(text: str, cmd: str, title: str = "") -> None:  # noqa: ARG001
    """Page through text by invoking a program on a temporary file."""
    import tempfile  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tempdir:
        filename = os.path.join(tempdir, "pydoc.out")
        encoding = os.device_encoding(0) if sys.platform == "win32" else None

        def _write() -> None:
            with open(
                filename,
                "w",
                errors="backslashreplace",
                encoding=encoding,
            ) as file:
                file.write(text)

        await run_sync(_write)
        try:
            await run(
                *shlex.split(cmd),
                filename,
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        except CalledProcessError:
            pass  # the pager returned nonzero
