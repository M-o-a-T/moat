"""
Installation and setup.
"""

from __future__ import annotations

import anyio
import logging
import os
import sys
from anyio import Path as FSPath
from contextlib import suppress
from pprint import pformat
from shutil import copy as copy_fs
from shutil import copytree as copytree_fs
from shutil import rmtree

import asyncclick as click

from moat.util import NotGiven, P, Path, merge, ungroup
from moat.lib.codec import get_codec
from moat.micro.cmd.tree.dir import Dispatch
from moat.micro.cmd.util.part import get_part
from moat.micro.util import run_update
from moat.util.compat import idle, log
from moat.util.exec import run as run_cmd

logger = logging.getLogger(__name__)

all = ["setup", "install", "do_update", "do_copy"]  # noqa: A001


async def do_update(dst, root, cross, hfn):  # noqa: D103
    from moat.micro.path import copytree  # noqa: PLC0415

    await run_update(dst / "lib", cross=cross, hash_fn=hfn)

    # do not use "/". Running micropython tests locally requires
    # all satellite paths to be relative.
    import moat.micro._embed  # noqa: PLC0415

    p = anyio.Path(moat.micro._embed.__path__[0])  # noqa:SLF001
    await copytree(p / "boot.py", root / "boot.py", cross=None)
    if not await (root / "main.py").exists():
        await copytree(p / "main.py", root / "main.py", cross=None)


async def do_copy(
    source: anyio.Path,
    dst: anyio.Path,
    dest: str | None,
    cross: str,
    wdst: anyio.Path | None = None,
):
    """
    Copy from source to @dst/@dest.

    if @dest is `None`, append the source path behind ``/_embed/`` (if it exists).

    @cross is the path of the mpy-cross executable.
    """
    from .path import copy_over  # noqa: PLC0415

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
    install: bool = False,
    source: anyio.Path | None = None,
    root: str = ".",
    dest: str = "",
    kill: bool = False,
    large: bool | None = None,
    run: bool | dict = False,
    rom: bool = False,
    reset: bool = False,
    state: str | None = None,
    config: dict | None = None,
    cross: str | None = None,
    update: bool = False,
    mount: bool = False,
    watch: bool = False,
    main: str = False,
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

    from .direct import DirectREPL  # noqa: PLC0415
    from .path import ABytes, MoatDevPath, copy_over  # noqa: PLC0415
    from .proto.stream import RemoteBufAnyio  # noqa: PLC0415

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

    need_run = False

    if main == "-":
        main = None
    elif main is None and "install" in cfg:
        main = cfg.install.get("main", None)
        if main is NotGiven:
            main = None
        else:
            import moat.micro._embed  # noqa: PLC0415

            main = cfg.install.get("main", anyio.Path(moat.micro._embed.__path__[0]) / "main.py")  # noqa:SLF001

    # The following dance is necessary because a reset may or may not kill
    # the whole stack. Fixing this, i.e. making individual apps fault
    # tolerant, is somewhere on the TODO list.

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
                from moat.micro.fuse import wrap  # noqa: PLC0415

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
                merge(dsp.cfg, run)
                await dsp.reload()
                log("Running.")
                cons = b""
                while True:
                    try:
                        with anyio.fail_after(3):
                            (m,) = await dsp.cmd(P("s.crd"))
                        cons += m
                        if cons.endswith(b"\nOK\x04\x04>"):
                            break
                    except TimeoutError:
                        break
                if cons:
                    log("Console:\n%s", cons.decode("utf-8", errors="replace"))
                async with dsp.sub_at(dsp.cfg.remote2) as sr:
                    try:
                        print(await sr.dir_())
                        await sr.s.ping()
                    except Exception as exc:
                        logger.error("PROBLEM %r", exc)
                    need_run = False
                    log("RUNNING.")
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
                    from .romfs import make_romfs, write_rom  # noqa:PLC0415

                    async with anyio.TemporaryDirectory() as tf:
                        await do_copy(source, dst, dest, cross, wdst=tf)
                        rom = await make_romfs(tf)
                        await write_rom(sd, tf)
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
                logger.debug("Config:\n%s", pformat(config))
                f = ABytes(name="moat.cfg", data=codec.encode(config))
                await copy_over(f, MoatDevPath("moat.cfg").connect_repl(repl))

            if main:
                from moat.micro.path import copytree  # noqa: PLC0415

                await copytree(
                    anyio.Path(main), MoatDevPath(".").connect_repl(repl) / "main.py", cross=None
                )

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

        logger.warning(
            "Reset: caused %r", exc, exc_info=exc if logger.isEnabledFor(logging.DEBUG) else None
        )

        await anyio.sleep(3)
        async with (
            Dispatch(cfg, run=True) as dsp,
            dsp.sub_at(cfg.remote) as sd,
        ):
            log("Running after reset.")
            await part_two()


def find_p(prog: str):
    """
    Find an executable in the system path.
    """
    for p in os.environ["PATH"].split(os.pathsep):
        try:
            pp = p + os.sep + prog
            os.stat(pp)
        except FileNotFoundError:
            continue
        else:
            return pp

    return None


async def install_(cfg, dest: Path = None):
    """
    Install our version of MicroPython to a device.
    """
    device = cfg.install.port
    board = cfg.install.get("board", None)
    variant = cfg.install.get("variant", None)

    mydir = FSPath(__file__).parent.parent.parent
    mpydir = mydir / "ext" / "micropython"
    portdir = mpydir / "ports" / device

    boardp = f"{board or 'generic'}{f'-{variant}' if variant else ''}"

    board_dir = FSPath(__file__).parent / "_embed" / "boards" / device / board
    if await board_dir.exists():
        board_arg = f"{device}_moat{os.getpid()}"
        board_tmp = portdir / "boards" / board_arg
    else:
        board_tmp = None
        board_dir = board_arg = boardp
        if not await (portdir / board_dir).exists():
            board_dir = None
    board_arg = str(anyio.Path("boards") / board_arg)

    try:
        raise OSError("doesn't work")
        build_dir = FSPath(cfg.install.build)
        if not await build_dir.exists():
            await build_dir.mkdir()

        buildp = f"build-{os.getpid()}"
        build_tmp = portdir / buildp
    except OSError:
        buildp = f"build-{boardp}"
        build_dir = buildp
        build_tmp = None

    if isinstance(cfg.install.serial, str):
        port = anyio.Path(cfg.install.serial)
    else:
        try:
            port = anyio.Path(get_part(cfg, cfg.install.serial))
        except AttributeError:
            port = None
    try:
        rate = cfg.install.rate
    except AttributeError:
        rate = None

    if device == "rp2" and dest is None:
        raise ValueError("Installing to Raspberry Pi Pico requires a 'dest' directory")

    args = []

    if device == "esp32":
        idf = find_p("idf.py")
        if idf is None:
            if "ESP" not in os.environ:
                raise click.UsageError(
                    "'idf.py' not found: Source $ESP/export.sh and try again.",
                )
            idf = os.environ["ESP"] + os.sep + "idf.py"

    if device in ("esp32", "esp8266"):
        goal = "deploy"
        args.append("ESPTOOL=esptool")

    else:
        goal = "all"
        # if board is None:
        #     board = "rpi_pico"

    import moat.micro._embed._tag as m  # noqa: PLC0415

    manifest = m.__file__.replace("_tag", "manifest")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(await anyio.Path.absolute(mydir))

    try:
        if build_tmp:
            await (build_tmp).symlink_to(build_dir)
        if board_tmp:
            await anyio.to_thread.run_sync(copytree_fs, str(board_dir), str(board_tmp))

        await run_cmd(
            "make",
            "-j",
            cwd=str(mpydir / "mpy-cross"),
            echo=True,
        )
        await run_cmd(
            "make",
            "-j",
            "PORT=" + str(port),
            "BAUD=" + str(rate),
            "BOARD=" + board,
            "BOARD_DIR=" + board_arg,
            "BUILD=" + buildp,
            "FROZEN_MANIFEST=" + manifest,
            *args,
            goal,
            cwd=portdir,
            env=env,
            echo=True,
        )
    finally:
        with anyio.move_on_after(2, shield=True):
            if build_tmp:
                with suppress(OSError), ungroup:
                    await (portdir / build_tmp).unlink()
            if board_tmp:
                with suppress(OSError), ungroup:
                    await anyio.to_thread.run_sync(rmtree, str(board_tmp))

    if device == "rp2":
        if isinstance(dest, str):
            dest = anyio.Path(dest)
        df = dest / "INFO_UF2.TXT"
        if not await df.exists():
            print(f"Waiting for RPI in {dest} ", end="")
            sys.stdout.flush()
            while not await df.exists():  # noqa:ASYNC110
                # not going to import inotify just for this
                await anyio.sleep(1)
            print("… found.")

        await anyio.to_thread.run_sync(
            copy_fs,
            portdir / "build-RPI_PICO/" / "firmware.uf2",
            dest,
        )

    if port is not None and not await port.exists():
        print(f"Waiting for RPI in {dest} ", end="")
        sys.stdout.flush()
        while not await port.exists():  # noqa:ASYNC110
            # not going to import inotify just for this
            await anyio.sleep(1)
        print("… found.")

    await setup(
        cfg,
        run=True,
        update=True,
        state="once",
        cross=mpydir / "mpy-cross" / "build" / "mpy-cross",
    )
