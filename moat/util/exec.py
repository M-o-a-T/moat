"""
This module contains a helper for running subprocesses.
"""

from __future__ import annotations

import anyio
import io
from codecs import getincrementaldecoder
from pathlib import Path
from subprocess import DEVNULL, PIPE, STDOUT, CalledProcessError

from typing import TYPE_CHECKING, cast, overload

if TYPE_CHECKING:
    from io import BytesIO

    from collections.abc import AsyncIterable
    from typing import Literal


__all__ = ["DEVNULL", "PIPE", "STDOUT", "CalledProcessError", "run"]


@overload
async def run(
    *a,
    name: str | None = None,
    echo: bool = False,
    echo_input: bool = False,
    capture=False,
    input: str | bytes | None = None,
    **kw,
) -> None:
    "no data"


@overload
async def run(
    *a,
    name: str | None = None,
    echo: bool = False,
    echo_input: bool = False,
    capture="raw",
    input: str | bytes | None = None,
    **kw,
) -> bytes:
    "raw data"


@overload
async def run(
    *a,
    name: str | None = None,
    echo: bool = False,
    echo_input: bool = False,
    capture=True,
    input: str | bytes | None = None,
    **kw,
) -> str:
    "string data"


async def run(
    *a,
    name=None,
    echo=False,
    echo_input=False,
    capture: bool | Literal["raw"] = False,
    input=None,  # noqa: A002
    **kw,
) -> None | str | bytes:
    """Helper to run an external program, tagging stdout/stderr"""

    if name is None:
        name = ""
    else:
        name += " "
    if echo:
        print(name + "$", *a, *(("<", repr(kw["input"])) if echo_input and "input" in kw else ()))
    if input is None:
        if "stdin" not in kw:
            kw["stdin"] = DEVNULL
    else:
        if isinstance(input, str):
            input = input.encode("utf-8")  # noqa: A001

    if capture and kw.get("stdout", PIPE) != PIPE:
        raise ValueError("can't capture if stdout is not PIPE")

    if isinstance((cwd := kw.get("cwd")), (anyio.Path, Path)):
        kw["cwd"] = str(cwd)

    frag = None
    out = None
    err = None

    async def report(prefix: str, stream: AsyncIterable[bytes], buf: BytesIO):
        nonlocal frag
        utf = getincrementaldecoder("utf-8")()
        async for chunk in stream:
            buf.write(chunk)
            if not echo:
                continue
            chunk = utf.decode(chunk).split("\n")  # noqa:PLW2901
            lch = chunk.pop()
            if frag not in (None, stream):
                print("…")

            for ch in chunk:
                print(prefix, ch)

            if lch:
                print(prefix, lch, end="")
                frag = stream
            else:
                frag = None

    async with (
        await anyio.open_process(a, **kw) as proc,
        anyio.create_task_group() as tg,
    ):
        if proc.stdout:
            out = io.BytesIO()
            tg.start_soon(report, name + ">", proc.stdout, out)
        if proc.stderr:
            err = io.BytesIO()
            tg.start_soon(report, name + "⫸", proc.stderr, err)
        if input is not None:
            await proc.stdin.send(input)
            await proc.stdin.aclose()

    if frag is not None:
        print("…")

    if proc.returncode != 0:
        raise CalledProcessError(
            cast(int, proc.returncode),
            a,
            None if out is None else out.getvalue(),
            None if err is None else err.getvalue(),
        )

    if capture:
        res = out.getvalue()
        if capture is True:
            res = res.decode("utf-8")
        return res

    return None
