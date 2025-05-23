"""
Installation and setup.
"""

from __future__ import annotations

import anyio
import logging
import os
import sys
import shutil

from moat.util import merge, P
from moat.micro.cmd.tree.dir import Dispatch
from moat.micro.cmd.util.part import get_part
from moat.micro.util import run_update
from moat.lib.codec import get_codec
from moat.util.compat import idle, log

import asyncclick as click
import contextlib

logger = logging.getLogger(__name__)

all = ["setup", "install", "do_update", "do_copy"]


async def do_update(dst, root, cross, hfn):
    from moat.micro.path import copytree

    await run_update(dst / "lib", cross=cross, hash_fn=hfn)

    # do not use "/". Running micropython tests locally requires
    # all satellite paths to be relative.
    import moat.micro._embed

    p = anyio.Path(moat.micro._embed.__path__[0])  # noqa:SLF001
    await copytree(p / "boot.py", root / "boot.py", cross=None)
    await copytree(p / "main.py", root / "main.py", cross=None)


async def do_copy(source:anyio.Path, dst:anyio.Path, dest:str|None, cross:str, wdst:anyio.Path|None=None):
    """
    Copy from source to @dst/@dest.

    if @dest is `None`, append the source path behind ``/_embed/`` (if it exists).

    @cross is the path of the mpy-cross executable.
    """
    from .path import copy_over

    if not dest:
        dest = str(source)
        pi = dest.find("/_embed/")
        if pi > 0:
            dest = dest[pi + 8 :]
            dst /= dest
    else:
        dst /= dest
    await copy_over(source, dst, cross=cross, wdst=wdst)


def _clean_cfg(cfg):
    # cfg = attrdict(apps=cfg["apps"])  # drop all the other stuff
    return cfg


async def setup(
    cfg,
    install:bool=False,
    source:anyio.Path|None=None,
    root:str=".",
    dest:str="",
    kill:bool=False,
    large:bool|None=None,
    run:bool=False,
    rom:bool=False,
    reset:bool=False,
    state:str|None=None,
    config:dict|None=None,
    cross:str|None=None,
    update:bool=False,
    mount:bool=False,
    watch:bool=False,
):
    """
    Given the serial link to a MicroPython board,
    teach it to run the MoaT loop.

    Parameters: see "moat micro setup --help".
    """
    # 	if not source:
    # 		source = anyio.Path(__file__).parent / "_embed"

    if bool(watch) + bool(run) + bool(mount) > 1:
        raise click.UsageError("You can only use one of 'watch','mount', and 'run'.")

    if install:
        await install_(cfg, dest=dest)
        print("Firmware installation done.", file=sys.stderr)

    from .direct import DirectREPL
    from .path import ABytes, MoatDevPath, copy_over
    from .proto.stream import RemoteBufAnyio

    codec = get_codec("std-cbor")

    if cross == "-":
        cross = None

    if kill:
        async with (
            Dispatch(cfg, run=True) as dsp,
            dsp.sub_at(cfg.remote) as sd,
            RemoteBufAnyio(sd) as ser,
            DirectREPL(ser) as repl,
        ):
            dst = MoatDevPath(root).connect_repl(repl)
            await repl.reset()
        await anyio.sleep(2)

    # The following dance is necessary because a reset may or may not kill
    # the whole stack. Fixing this, i.e. making individual apps fault
    # tolerant, is somewhere on the TODO list.

    need_run = False

    async def part_two():
        nonlocal need_run
        if run or watch or mount:
            if run and not reset:
                o, e = await repl.exec_raw(
                    f"from main import go; go(state={state!r})",
                    timeout=None if watch else 30,
                )
                if o:
                    print(o)
                if e:
                    print("ERROR", file=sys.stderr)
                    print(e, file=sys.stderr)
                    sys.exit(1)

            if watch:
                while True:
                    d = await ser.receive()
                    sys.stderr.buffer.write(d)
                    sys.stderr.buffer.flush()

            if mount:
                from moat.micro.fuse import wrap

                async with (
                    dsp.sub_at(cfg["path"] / f) as fs,
                    wrap(
                        fs,
                        mount,
                        blocksize=cfg.get("blocksize", 64),
                        debug=4,
                    ),
                ):
                    await idle()

            if run:
                log("Reloading.")
                merge(dsp.cfg, run, drop=True)
                await dsp.reload()
                log("Running.")
                await sd.dispatch(P("_s.ping"))
                need_run = False
                await idle()

    try:
        async with (
            Dispatch(cfg, run=True) as dsp,
            dsp.sub_at(cfg.remote) as sd,
            RemoteBufAnyio(sd) as ser,
            DirectREPL(ser) as repl,
        ):
            dst = MoatDevPath(root).connect_repl(repl)
            if source:
                if rom:
                    async with anyio.TemporaryDirectory() as wdst:
                        breakpoint()
                        await do_copy(source, dst, dest, cross, wdst=tf)
                        rom = await make_romfs(tf)
                        await write_rom(tf)
                else:
                    await do_copy(source, dst, dest, cross)
            if state and not watch:
                await repl.exec(f"f=open('moat.state','w'); f.write({state!r}); f.close(); del f")
            if large is True:
                await repl.exec("f=open('moat.lrg','w'); f.close()", quiet=True)
            elif large is False:
                await repl.exec("import os; os.unlink('moat.lrg')", quiet=True)

            if config:
                config = _clean_cfg(config)
                f = ABytes(name="moat.cfg", data=codec.encode(config))
                await copy_over(f, MoatDevPath("moat.cfg").connect_repl(repl))

            if update:

                async def hfn(p):
                    res = await repl.exec(
                        f"import _hash; print(repr(_hash.hash[{p!r}])); del _hash",
                        quiet=True,
                    )
                    return eval(res)

                await do_update(dst, MoatDevPath(".").connect_repl(repl), cross, hfn)

            need_run = True
            if reset:
                await repl.soft_reset(run_main=bool(run))
                # reset with run_main set should boot into MoaT

            await part_two()

    except Exception as exc:
        if not need_run:
            raise

        log("Reset: caused %r", exc)

        await anyio.sleep(3)
        async with (
            Dispatch(cfg, run=True) as dsp,
            dsp.sub_at(cfg.remote) as sd,
        ):
            log("Running after reset.")
            await part_two()


def find_p(prog: str):
    for p in os.environ["PATH"].split(os.pathsep):
        try:
            pp = p + os.sep + prog
            os.stat(pp)
        except FileNotFoundError:
            continue
        else:
            return pp

    return None


async def install_(cfg, dest: Path = None, upload: bool = False):
    device = cfg.install.port
    try:
        port = anyio.Path(get_part(cfg, cfg.install.serial))
    except AttributeError:
        port = None
    with contextlib.suppress(AttributeError):
        pass
    try:
        rate = cfg.install.rate
    except AttributeError:
        rate = None
    try:
        board = cfg.install.board
    except AttributeError:
        board = None

    if device == "rp2" and dest is None:
        raise ValueError("Installing to Raspberry Pi Pico requires a 'dest' directory")
    if device == "esp32":
        idf = find_p("idf.py")
        if idf is None:
            if "ESP" not in os.environ:
                raise click.UsageError(
                    "'idf.py' not found: Try ESP=/path/to/src/esp-idf, or source $ESP/export.sh",
                )
            idf = os.environ["ESP"] + os.sep + "idf.py"
        goal = "deploy"
        if board is None:
            board = "esp32_generic"

    elif device == "esp8266":
        goal = "deploy"
        if board is None:
            board = "esp8266_generic"

    else:
        goal = "all"
        if board is None:
            board = "rpi_pico"

    import moat.micro._embed._tag as m

    manifest = m.__file__.replace("_tag", "manifest")

    mpydir = anyio.Path("ext") / "micropython"
    portdir = mpydir / "ports" / device
    await anyio.run_process(
        [
            "make",
            "-j",
            "ESPTOOL=esptool",
            "PORT=" + str(port),
            "BAUD=" + str(rate),
            "BOARD=" + board.upper(),
            "FROZEN_MANIFEST=" + manifest,
            goal,
        ],
        cwd=portdir,
        check=True,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env={"PYTHONPATH": await anyio.Path.cwd()},
    )

    if device == "rp2":
        if isinstance(dest, str):
            dest = anyio.Path(dest)
        df = dest / "INFO_UF2.TXT"
        if not await df.exists():
            print(f"Waiting for RPI in {dest} ", end="")
            sys.stdout.flush()
            while not await df.exists():
                await anyio.sleep(1)
            print("… found.")

        await anyio.to_thread.run_sync(
            shutil.copy,
            portdir / "build-RPI_PICO/" / "firmware.uf2",
            dest,
        )

    if port is not None and not await port.exists():
        print(f"Waiting for RPI in {dest} ", end="")
        sys.stdout.flush()
        while not await port.exists():
            await anyio.sleep(1)
        print("… found.")

    await setup(
        cfg,
        run=True,
        update=True,
        state="once",
        cross=mpydir / "mpy-cross" / "build" / "mpy-cross",
    )
