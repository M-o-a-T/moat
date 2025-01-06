"""
Command-line code for moat.micro
"""

# pylint: disable=import-outside-toplevel
from __future__ import annotations

import anyio
import logging
import sys
from functools import wraps

from moat.util import (
    NotGiven,
    P,
    Path,
    attr_args,
    combine_dict,
    merge,
    packer,
    process_args,
    to_attrdict,
    ungroup,
    unpacker,
    yload,
    yprint,
)
from moat.micro.cmd.tree.dir import Dispatch, SubDispatch
from moat.micro.cmd.util.part import get_part
from moat.micro.errors import NoPathError, RemoteError
from moat.micro.path import copytree
from moat.micro.stacks.util import TEST_MAGIC
from moat.micro.util import run_update
from moat.util.main import load_subgroup

from .compat import idle, log

import asyncclick as click

logger = logging.getLogger(__name__)


def _clean_cfg(cfg):
    # cfg = attrdict(apps=cfg["apps"])  # drop all the other stuff
    return cfg


skip_exc = {FileNotFoundError, FileExistsError, ConnectionRefusedError}


def catch_errors(fn):
    """
    Wrapper for commands so that some errors don't cause a stack trace.
    """

    @wraps(fn)
    async def wrapper(*a, **k):
        try:
            with ungroup:
                return await fn(*a, **k)
        except (NoPathError, ConnectionRefusedError) as e:
            raise click.ClickException(e)  # noqa:B904
        except Exception as e:
            if "bdb" in sys.modules:
                skip_exc.add(sys.modules["bdb"].BdbQuit)
            if type(e) in skip_exc:
                raise click.ClickException(repr(e))  # noqa:B904
            raise

    return wrapper


@load_subgroup(
    prefix="moat.micro",
    epilog="""
        The 'section' parameter says which part of the configuration to use.
        for connecting to the remote system. The defaults are:

        \b
        Command  Section
        =======  =======
        run      :          the config file's root
        setup    setup
        *        connect    used for all other commands

        The 'remote' parameter specifies the prefix that connects to
        the remote system.

        The '--path NAME P' parameter is a shorthand for
            "moat -p micro.connect.path.NAME P micro …"
        """,
)
@click.pass_context
@click.option("-S", "--section", type=P, help="Section to use")
@click.option("-R", "--remote", type=P, help="path to the satellite")
@click.option("-P", "--path", type=(str, P), multiple=True, help="remote's component")
async def cli(ctx, section, remote, path):
    """Run MicroPython satellites

    'moat micro' configures MoaT satellites and runs the link to them,
    as well as applications using it."""
    obj = ctx.obj
    obj.ocfg = cfg = obj.cfg["micro"]
    inv = ctx.invoked_subcommand
    if inv == "run":
        if remote is not None:
            raise click.UsageError("You don't use a remote with 'moat micro run'")
        if path:
            raise click.UsageError("You don't use paths with 'moat micro run'")
        if section is None:
            section = Path()
    elif inv == "setup":
        if path:
            raise click.UsageError("You don't use paths with 'moat micro run'")
        if section is None:
            section = Path("setup")
    else:
        if section is None:
            section = Path("connect")
    try:
        cfg = get_part(cfg, section)
    except KeyError:
        cfg = {}

    if remote is not None:
        cfg["remote"] = remote
    elif "remote" not in cfg:
        cfg["remote"] = P("r")
    pth = cfg.setdefault("path", {})
    for n, p in path:
        cfg["path"][n] = p
    for k, v in pth.items():
        if isinstance(v, str):
            v = P(v)  # noqa:PLW2901
        pth[k] = cfg["remote"] + v

    obj.cfg = to_attrdict(cfg)


async def _do_update(dst, root, cross, hfn):
    await run_update(dst / "lib", cross=cross, hash_fn=hfn)

    # do not use "/". Running micropython tests locally requires
    # all satellite paths to be relative.
    import moat.micro._embed

    p = anyio.Path(moat.micro._embed.__path__[0])  # noqa:SLF001
    await copytree(p / "boot.py", root / "boot.py", cross=None)
    await copytree(p / "main.py", root / "main.py", cross=None)


async def _do_copy(source, dst, dest, cross):
    from .path import copy_over

    if not dest:
        dest = str(source)
        pi = dest.find("/_embed/")
        if pi > 0:
            dest = dest[pi + 8 :]
            dst /= dest
    else:
        dst /= dest
    await copy_over(source, dst, cross=cross)


@cli.command(name="setup", short_help="Copy MoaT to MicroPython")
@click.pass_context
@click.option("-r", "--run", is_flag=True, help="Run MoaT after updating")
@click.option("-N", "--reset", is_flag=True, help="Reboot after updating")
@click.option("-K", "--kill", is_flag=True, help="Reboot initially")
@click.option(
    "-S",
    "--source",
    type=click.Path(dir_okay=True, file_okay=True, path_type=anyio.Path),
    help="Files to sync",
)
@click.option("-D", "--dest", type=str, default="", help="Destination path")
@click.option("-R", "--root", type=str, default=".", help="Destination root")
@click.option("-U/-V", "--update/--no-update", is_flag=True, help="Run standard updates")
@click.option(
    "-M",
    "--mount",
    type=click.Path(dir_okay=True, file_okay=False),
    help="Mount point for FUSE mount",
)
@click.option("-l/-L", "--large/--no-large", is_flag=True, help="Use more RAM")
@click.option("-s", "--state", type=str, help="State to enter by default")
@click.option("-c", "--config", type=P, help="Config part to use for the device")
@click.option("-w", "--watch", is_flag=True, help="monitor the target's output after setup")
@click.option("-C", "--cross", help="path to mpy-cross")
@catch_errors
async def setup_(ctx, **kw):
    """
    Initial sync of MoaT code to a MicroPython device.

    MoaT must not currently run on the target. If it does,
    send `` TBD `` commmands.
    """
    default = {
        k: v
        for k, v in kw.items()
        if ctx.get_parameter_source(k) == click.core.ParameterSource.DEFAULT
    }
    param = {
        k: v
        for k, v in kw.items()
        if ctx.get_parameter_source(k) != click.core.ParameterSource.DEFAULT
    }

    # teach the 'large' flag to be ternary
    if "large" in default:
        default["large"] = None

    obj = ctx.obj
    cfg = obj.cfg
    st = {
        k: (v if v != "-" else NotGiven) for k, v in cfg.setdefault("args", {}).items() if k in kw
    }

    st = combine_dict(param, st, default)
    return await setup(cfg, obj.ocfg, **st)


async def setup(
    cfg,
    ocfg,
    source=None,
    root=".",
    dest="",
    kill=False,
    large=None,
    run=False,
    reset=False,
    state=None,
    config=None,
    cross=None,
    update=False,
    mount=False,
    watch=False,
):
    "sync helper"
    # 	if not source:
    # 		source = anyio.Path(__file__).parent / "_embed"

    if bool(watch) + bool(run) + bool(mount) > 1:
        raise click.UsageError("You can't use 'watch','mount', or 'run' concurrently.")

    from .direct import DirectREPL
    from .path import ABytes, MoatDevPath, copy_over
    from .proto.stream import RemoteBufAnyio

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

    async with (
        Dispatch(cfg, run=True) as dsp,
        dsp.sub_at(cfg.remote) as sd,
        RemoteBufAnyio(sd) as ser,
        DirectREPL(ser) as repl,
    ):
        dst = MoatDevPath(root).connect_repl(repl)
        if source:
            await _do_copy(source, dst, dest, cross)
        if state and not watch:
            await repl.exec(f"f=open('moat.state','w'); f.write({state!r}); f.close(); del f")
        if large is True:
            await repl.exec("f=open('moat.lrg','w'); f.close()", quiet=True)
        elif large is False:
            await repl.exec("import os; os.unlink('moat.lrg')", quiet=True)

        if config:
            config = _clean_cfg(get_part(ocfg, config))
            f = ABytes(name="moat.cfg", data=packer(config))
            await copy_over(f, MoatDevPath("moat.cfg").connect_repl(repl))

        if update:

            async def hfn(p):
                res = await repl.exec(
                    f"import _hash; print(repr(_hash.hash[{p!r}])); del _hash",
                    quiet=True,
                )
                return eval(res)  # noqa: S307

            await _do_update(dst, MoatDevPath(".").connect_repl(repl), cross, hfn)
        if reset:
            await repl.soft_reset(run_main=run)
            # reset with run_main set should boot into MoaT

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
                    SubDispatch(dsp, cfg["path"] + (f,)) as fs,
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
                merge(dsp.cfg, ocfg, drop=True)
                await dsp.reload()
                log("Running.")
                await idle()


@cli.command("sync", short_help="Sync MoaT code")
@click.pass_context
@click.option(
    "-s",
    "--source",
    type=click.Path(dir_okay=True, file_okay=True, path_type=anyio.Path),
    multiple=True,
    help="more files to sync",
)
@click.option("-d", "--dest", type=str, default=".", help="Destination path")
@click.option("-C", "--cross", help="path to mpy-cross")
@click.option("-B/-b", "--boot/--no-boot", help="Reboot after updating")
@click.option("-U/-V", "--update/--no-update", is_flag=True, help="Run standard updates")
@catch_errors
async def sync_(ctx, **kw):
    """
    Sync of MoaT code on a running MicroPython device.

    """
    from .path import MoatFSPath

    obj = ctx.obj
    cfg = obj.cfg

    default = {
        k: v
        for k, v in kw.items()
        if ctx.get_parameter_source(k) == click.core.ParameterSource.DEFAULT
    }
    param = {
        k: v
        for k, v in kw.items()
        if ctx.get_parameter_source(k) != click.core.ParameterSource.DEFAULT
    }
    st = {k: (v if v != "-" else NotGiven) for k, v in cfg.get("sync", {}).items() if k in kw}
    st = combine_dict(param, st, default)

    async def syn(source=(), dest=".", cross=None, update=False, boot=False):
        if cross == "-":
            cross = None
        dest = dest.lstrip("/")  # needs to be relative
        if not update and not source:
            if obj.debug:
                print("Nothing to do.", file=sys.stderr)
            return
        if dest is None:
            raise click.UsageError("Destination cannot be empty")
        async with (
            Dispatch(cfg, run=True) as dsp,
            SubDispatch(dsp, cfg.path.fs) as rfs,
            SubDispatch(dsp, cfg.path.sys) as rsys,
        ):
            root = MoatFSPath("/").connect_repl(rfs)
            dst = MoatFSPath(dest).connect_repl(rfs)

            async def hsh(p):
                return await rsys.hash(p=p)

            if update:
                await _do_update(dst, root, cross, hsh)
            for s in source:
                await _do_copy(s, root, dest, cross)
            if boot:
                await rsys.boot(code="SysBooT", m=1)

    await syn(**st)


@cli.command(short_help="Reboot MoaT node")
@click.pass_obj
@click.option("-s", "--state", help="State after reboot")
@catch_errors
async def boot(obj, state):
    """
    Restart a MoaT node

    """
    cfg = obj.cfg
    async with Dispatch(cfg) as dsp, SubDispatch(dsp, cfg.path.sys) as sd:
        if state:
            await sd.state(state=state)

        # reboot via the multiplexer
        logger.info("Rebooting target.")
        await sd.boot()

        # await t.send(["sys","boot"], code="SysBooT")
        await anyio.sleep(2)

        res = await sd("test")
        assert res == TEST_MAGIC, res

        res = await sd("ping", m="pong")
        if res != "R:pong":
            raise RuntimeError("wrong reply")
        print("Success:", res)


@cli.command(short_help="Send a MoaT command")
@click.pass_obj
@click.argument("path", nargs=1, type=P)
@attr_args(with_path=True, with_proxy=True)
@catch_errors
async def cmd(obj, path, **attrs):
    """
    Send a MoaT command.

    The command is prefixed by the "micro.connect.remote" option;
    use "moat micro -R ‹path› cmd …" to change it if necessary.

    The item "_a" is an empty array, for positional arguments.
    Use `-e/-v/-p _a:n XXX` to append to it.
    """
    cfg = obj.cfg
    val = {"_a":[]}
    val = process_args(val, no_path=True, **attrs)
    if len(path) == 0:
        raise click.UsageError("Path cannot be empty")
    logger.debug(
        "Command: %s %s",
        cfg.remote + path,
        " ".join(f"{k}={v!r}" for k, v in val.items()),
    )
    a = val.pop("_a", ())

    async with Dispatch(cfg, run=True) as dsp, SubDispatch(dsp, cfg.remote) as sd:
        try:
            res = await sd.dispatch(tuple(path), val)
        except RemoteError as err:
            yprint(dict(e=str(err.args[0])), stream=obj.stdout)
        else:
            yprint(res, stream=obj.stdout)


@cli.command("cfg", short_help="Get / Update the configuration")
@click.pass_obj
@click.option("-r", "--read", type=click.File("r"), help="Read config from this file")
@click.option("-R", "--read-client", help="Read config file from the client")
@click.option("-w", "--write", type=click.File("w"), help="Write config to this file")
@click.option("-S", "--stdout", is_flag=True, hidden=True)
@click.option("-W", "--write-client", help="Write config file to the client")
@click.option("-s", "--sync", is_flag=True, help="Sync the client after writing")
@click.option(
    "-c",
    "--client",
    is_flag=True,
    help="The client's data win if both -r and -R are used",
)
@attr_args(with_proxy=True)
@catch_errors
async def cfg_(
    obj,
    read,
    read_client,
    write,
    write_client,
    sync,
    stdout,
    client,
    **attrs,
):
    """
    Update a remote configuration.

    The remote config is updated online if you only use "-v -e -P"
    arguments. No output is printed in this case, and the config is not
    read from the client.

    Otherwise, the configuration is read as YAML from stdin (``-r -``) or a
    file (``-r PATH``), as msgpack from Flash (``-R xx.cfg``), or from the
    client's memory (``-R -``; this is the default if neither ``-r`` nor
    ``-R`` are used).

    It is then modified according to the "-v -e -P" arguments (if any) and
    written to Flash (``-W xx.cfg``), a file(``-w PATH``), stdout (``-w -``),
    or the client's live config (no ``-w``/``-W`` argument).

    The client will not be updated if a ``-w``/``-W`` argument is present.
    If you want to update the client *and* write the config data to a file,
    simply do it in two steps.

    An "apps" section must be present if you write a complete configuration
    to the client.

    This command assumes that the remote system has a ``cfg.Cmd`` app at
    path "r.c", and a ``fs.Cmd`` app at path "r.f". You can change the "r"
    part with the ``moat micro -L ‹name› cfg …``  option, and the others
    with ``… cfg --fs-path ‹path›`` and ``… cfg --fs-path ‹path›``.
    """
    if write and stdout:
        raise click.UsageError("no -S and -w")
    if stdout:
        write = obj.stdout

    if sync and (write or write_client):
        raise click.UsageError("You're not changing the running config!")

    cfg = obj.cfg

    if read and write and not (read_client or write_client):
        # local file update: don't talk to the client
        if client or sync:
            raise click.UsageError("You're not talking to the client!")

        cfg = yload(read)
        cfg = process_args(cfg, **attrs)
        yprint(cfg, stream=write)
        return

    if read_client or write_client:
        from .path import MoatFSPath

    async with (
        Dispatch(obj.cfg, run=True, sig=True) as dsp,
        dsp.cfg_at(cfg.path.cfg) as cf,
        dsp.sub_at(cfg.path.fs) as fs,
    ):
        has_attrs = any(a for a in attrs.values())

        if has_attrs and not (read or read_client or write or write_client):
            # No file access at all. Just update the client's RAM.

            val = process_args({}, **attrs)
            await cf.set(val, sync=sync)
            return

        if read:
            cfg = yload(read)
        if read_client:
            p = MoatFSPath(read_client).connect_repl(fs)
            d = await p.read_bytes(chunk=64)
            if not read:
                cfg = unpacker(d)
            elif client:
                cfg = merge(cfg, unpacker(d), replace=True)
            else:
                cfg = merge(cfg, unpacker(d), replace=False)
        if not read and not read_client:
            cfg = await cf.get()

        cfg = process_args(cfg, **attrs)
        if not write:
            if "apps" not in cfg:
                raise click.UsageError("No 'apps' section.")
            if not write_client:
                await cf.set(cfg, sync=sync, replace=True)

        if write_client:
            p = MoatFSPath(write_client).connect_repl(fs)
            d = packer(cfg)
            await p.write_bytes(d, chunk=64)
        if write:
            yprint(cfg, stream=write)
        if not has_attrs and not write and not write_client:
            yprint(cfg, stream=obj.stdout)


@cli.command("run", short_help="Run the multiplexer")
@click.pass_obj
@catch_errors
async def run_(obj):
    """
    Run the MoaT stack.
    """
    async with Dispatch(obj.cfg, run=True, sig=True):
        await idle()


@cli.command("mount")
@click.option("-b", "--blocksize", type=int, help="Max read/write message size", default=256)
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True), nargs=1)
@click.pass_obj
@catch_errors
async def mount_(obj, path, blocksize):
    """Mount a controller's file system on the host"""
    from moat.micro.fuse import wrap

    cfg = obj.cfg

    async with (
        Dispatch(cfg, run=True, sig=True) as dsp,
        SubDispatch(dsp, cfg.path.fs) as sd,
        wrap(sd, path, blocksize=blocksize, debug=max(obj.debug - 1, 0)),
    ):
        if obj.debug:
            print("Mounted.")
        await idle()


@cli.command("path")
@click.pass_obj
@click.option("-m", "--manifest", is_flag=True, help="main manifest")
@catch_errors
async def path_(obj, manifest):
    """Path to the embedded system's files"""

    import pathlib

    import moat.micro

    if manifest:
        import moat.micro._embed._tag as m

        print(m.__file__.replace("_tag", "manifest"), file=obj.stdout)
        return

    import moat.micro._embed

    for p in moat.micro._embed.__path__:  # noqa:SLF001
        p = pathlib.Path(p) / "lib"  # noqa:PLW2901
        if p.exists():
            print(p)
