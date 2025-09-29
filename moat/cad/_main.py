"""
This module dies some 3d stuff.
"""

from __future__ import annotations

import anyio

# pylint: disable=missing-module-docstring
import logging
from pathlib import Path as FSPath

import asyncclick as click

from moat.util import load_subgroup

logger = logging.getLogger(__name__)

usage1 = """
"moat cad" collects some useful bits and pieces for 3D editing with Python.
"""


@load_subgroup(sub_pre="moat.link", sub_post="cli", ext_pre="moat.link", ext_post="_main.cli")
@click.pass_context
async def cli(ctx):
    """
    MoaT 3D editor support.

    This collection of commands is useful for managing and building MoaT itself.
    """


@cli.command("edit")
@click.pass_obj
@click.argument("files", nargs=-1, default=None)
async def edit_(obj, files):
    "Start the editor."
    #    base: "/opt/cq"
    # paths:
    #  - "/src/CQ-editor"
    #  - "/src/build123d/src"
    #  - "/src/bd_warehouse/src"

    if len(files) > 1:
        raise click.UsageError("Max one file")

    import os  # noqa: PLC0415
    import sys  # noqa: PLC0415
    from tempfile import SpooledTemporaryFile  # noqa: PLC0415

    import moat  # noqa: PLC0415

    cfg = obj.cfg
    env = os.environ.copy()

    with SpooledTemporaryFile(mode="w+") as buf:
        await anyio.run_process(
            [f"{cfg.cad.base}/bin/python3", "-c", "import sys; print(repr(sys.path))"],
            stdout=buf,
        )
        buf.seek(0)
        pypath = (
            cfg.cad.paths
            + eval(buf.read())
            + [str(FSPath(p).parent.absolute()) for p in moat.__path__]
        )
    env["PYTHONPATH"] = os.pathsep.join(pypath)
    await anyio.run_process(
        [f"{cfg.cad.base}/bin/python3", "-mcq_editor"] + list(files),
        env=env,
        # stdin=subprocess.DEVNULL,
        stdout=sys.stdout,
        stderr=sys.stderr,
        # cwd: 'StrOrBytesPath | None' = None,
        # startupinfo: 'Any' = None,
        # creationflags: 'int' = 0,
        # start_new_session: 'bool' = False,
        # pass_fds: 'Sequence[int]' = (),
        # user: 'str | int | None' = None,
        # group: 'str | int | None' = None,
        # extra_groups: 'Iterable[str | int] | None' = None,
        # umask: 'int' = -1
    )


@cli.command("run")
@click.pass_obj
@click.argument("file", nargs=1)
@click.argument("args", nargs=-1)
async def run_(obj, file, args):
    "Run a script."

    import os  # noqa: PLC0415
    import sys  # noqa: PLC0415
    from tempfile import SpooledTemporaryFile  # noqa: PLC0415

    import moat  # noqa: PLC0415

    cfg = obj.cfg
    env = os.environ.copy()

    with SpooledTemporaryFile(mode="w+") as buf:
        res = await anyio.run_process(
            [f"{cfg.cad.base}/bin/python3", "-c", "import sys; print(repr(sys.path))"],
            stdout=buf,
        )
        buf.seek(0)
        pypath = (
            cfg.cad.paths
            + eval(buf.read())
            + [str(FSPath(p).parent.absolute()) for p in moat.__path__]
        )
    env["PYTHONPATH"] = os.pathsep.join(pypath)
    res = await anyio.open_process(
        [f"{cfg.cad.base}/bin/python3", file] + list(args),
        env=env,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        # cwd: 'StrOrBytesPath | None' = None,
        # startupinfo: 'Any' = None,
        # creationflags: 'int' = 0,
        # start_new_session: 'bool' = False,
        # pass_fds: 'Sequence[int]' = (),
        # user: 'str | int | None' = None,
        # group: 'str | int | None' = None,
        # extra_groups: 'Iterable[str | int] | None' = None,
        # umask: 'int' = -1
    )
    await res.wait()


@cli.command("gcode")
@click.option("-p", "--printer", type=str, default="xl")
async def gcode(printer):
    "Emit gcode template"
    from anyio import Path  # noqa: PLC0415

    from jinja2 import Environment  # noqa: PLC0415

    f = Path(__file__).parent / "_templates" / f"{printer}.gcode.jinja"
    env = Environment(
        keep_trailing_newline=True,
    )
    tmpl = env.from_string(await f.read_text())
    out = tmpl.render()
    print(out)
