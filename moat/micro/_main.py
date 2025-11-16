"""
Command-line code for moat.micro
"""

# pylint: disable=import-outside-toplevel
from __future__ import annotations

import anyio
import logging
import os
import sys
from functools import wraps

import asyncclick as click

from moat.util import (
    NotGiven,
    P,
    Path,
    attr_args,
    combine_dict,
    merge,
    process_args,
    to_attrdict,
    yload,
    yprint,
)
from moat.lib.cmd.msg import Msg
from moat.lib.codec import get_codec
from moat.lib.codec.errors import NoPathError, RemoteError
from moat.micro.cmd.tree.dir import Dispatch
from moat.micro.cmd.util.part import get_part
from moat.micro.stacks.util import TEST_MAGIC
from moat.util.compat import idle
from moat.util.main import load_subgroup

logger = logging.getLogger(__name__)


skip_exc = {FileNotFoundError, FileExistsError, ConnectionRefusedError}


def catch_errors(fn):
    """
    Wrapper for commands so that some errors don't cause a stack trace.
    """

    @wraps(fn)
    async def wrapper(*a, **k):
        try:
            return await fn(*a, **k)
        except (NoPathError, ConnectionRefusedError) as e:
            raise click.ClickException(e)  # noqa:B904
        except Exception as e:
            if "bdb" in sys.modules:
                skip_exc.add(sys.modules["bdb"].BdbQuit)
            if type(e) in skip_exc and "MOAT_TB" not in os.environ:
                raise click.ClickException(repr(e))  # noqa:B904
            raise

    return wrapper


@load_subgroup(
    prefix="moat.micro",
    epilog="""
        The 'section' parameter says which part of the MoaT configuration
        (below "moat.micro") to use to connect to the remote system.
        The defaults are:

        \b
        Command  Section
        =======  =======
        run      run        server mode
        setup,   setup      used for initial non-MoaT access to the device
         install
        *        connect    used for all other commands

        The 'remote' parameter specifies the prefix that talks to
        the remote system. The default is 'r'.

        """,
)
@click.pass_context
@click.option("-S", "--section", type=P, help="Section to use")
@click.option("-R", "--remote", type=P, help="Path for talking to the satellite")
@click.option("-P", "--path", type=(str, P), multiple=True, help="named remote component")
async def cli(ctx, section, remote, path):
    """Run MicroPython satellites

    'moat micro' configures MoaT satellites and runs the link to them,
    as well as applications using it."""
    obj = ctx.obj
    ocfg = cfg = obj.cfg.micro
    remote2 = None
    if "--help" in sys.argv:
        return  # HACK

    inv = ctx.invoked_subcommand
    if inv == "run":
        if remote is not None:
            raise click.UsageError("You don't use a remote with 'moat micro run'")
        if path:
            raise click.UsageError("You don't use paths with 'moat micro run'")
        if section is None:
            section = Path("run")
    elif inv in ("setup", "install"):
        if remote is not None:
            remote2, remote = remote, None
        else:
            remote2 = P("s")
        if path:
            raise click.UsageError("You don't use paths with 'moat micro setup|install'")
        if section is None:
            section = Path("setup")
    elif inv == "path":
        pass
    else:
        if section is None:
            section = Path("connect")
    if section is not None:
        try:
            cfg = get_part(cfg, section)
        except KeyError:
            raise click.UsageError(f"The config section '{section}' doesn't exist.") from None
    if remote2 is not None:
        cfg.remote2 = remote2
    try:
        cfg.args.config = get_part(ocfg, cfg.args.config)
    except (AttributeError, KeyError):
        if "args" in cfg and "config" in cfg.args:
            raise
        # otherwise no args section thus nothing to copy

    if remote is not None:
        cfg.remote = remote
    elif "remote" not in cfg:
        cfg.remote = P("r")
    pth = cfg.setdefault("path", {})
    for n, p in path:
        pth[n] = p
    for k, v in pth.items():
        if isinstance(v, str):
            v = P(v)  # noqa:PLW2901
        pth[k] = v

    obj.mcfg = to_attrdict(cfg)


@cli.command(name="setup", short_help="Copy MoaT to MicroPython")
@click.pass_context
@click.option("-i", "--install", is_flag=True, help="Install MicroPython")
@click.option("-r", "--run", is_flag=True, help="Run MoaT after updating")
@click.option("-F", "--rom", is_flag=True, help="Upload to ROM Flash")
@click.option("--run-section", type=P, help="Section with runtime config (default: 'run')")
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
@click.option(
    "-m",
    "--main",
    type=click.Path(dir_okay=False, readable=True, exists=True),
    help="file to use as main_.py",
)
@catch_errors
async def setup_(ctx, run_section=None, **kw):
    """
    Initial sync of MoaT code to a MicroPython device.

    MoaT must not currently run on the target.
    """
    from .setup import setup  # noqa: PLC0415

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

    cfg = ctx.obj.mcfg
    st = {
        k: (v if v != "-" else NotGiven) for k, v in cfg.setdefault("args", {}).items() if k in kw
    }

    st = combine_dict(param, st, default)

    run = st["run"]
    if run:
        if run_section is not None:
            st["run"] = ctx.obj.cfg.micro._get(run_section)  # noqa: SLF001
        else:
            try:
                st["run"] = ctx.obj.cfg.micro._get(P("setup.run"))  # noqa: SLF001
            except KeyError:
                st["run"] = ctx.obj.cfg.micro["run"]

    return await setup(cfg, **st)


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
    Sync of MoaT code to a running MicroPython device.

    """
    from .path import MoatFSPath  # noqa: PLC0415
    from .setup import do_copy, do_update  # noqa: PLC0415

    obj = ctx.obj
    cfg = obj.mcfg

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
            dsp.sub_at(cfg.remote) as cfr,
            cfr.sub_at(cfg.path.fs) as rfs,
            cfr.sub_at(cfg.path.sys) as rsys,
        ):
            root = MoatFSPath("/").connect_repl(rfs)
            dst = MoatFSPath(dest).connect_repl(rfs)

            async def hsh(p):
                return await rsys.hash(p=p)

            if update:
                await do_update(dst, root, cross, hsh)
            for s in source:
                await do_copy(s, root, dest, cross)
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
    cfg = obj.mcfg
    async with (
        Dispatch(cfg, run=True) as dsp,
        dsp.sub_at(cfg.remote) as cfr,
        cfr.sub_at(cfg.path.sys) as sd,
    ):
        if state:
            await sd.state(state=state)

        # reboot via the multiplexer
        logger.info("Rebooting target.")
        await sd.boot(code="SysBooT", m=1)

        # await t.send(["sys","boot"], code="SysBooT")
        await anyio.sleep(2)

        res = await sd("test")
        assert res == TEST_MAGIC, res

        res = await sd("ping", m="pong")
        if res != "R:pong":
            raise RuntimeError("wrong reply")
        print("Success:", res, file=sys.stderr)


@cli.command(short_help="Send a MoaT command")
@click.pass_obj
@click.argument("path", nargs=1, type=P)
@attr_args(with_path=True, with_proxy=True, with_arglist=True)
@click.option("-a", "--parts", is_flag=True, help="Retrieve a possibly-partial result")
@click.option("-t", "--time", is_flag=True, help="Time the command")
@catch_errors
async def cmd(obj, path, time, parts, **attrs):
    """
    Send a MoaT command.

    The command is prefixed by the "micro.connect.remote" option;
    use "moat micro -R ‹path› cmd …" to change it if necessary.

    Positional arguments may follow the command name. They are parsed as
    with `--set`.
    """
    cfg = obj.mcfg
    val = process_args({None: []}, no_path=True, **attrs)
    args = val.pop(None, ())
    logger.debug(
        "Command: %s %s %s",
        cfg.remote + path,
        "-" if not args else " ".join(str(a) for a in args),
        "-" if not val else " ".join(f"{k}={v!r}" for k, v in val.items()),
    )

    from time import monotonic as tm  # noqa: PLC0415

    from moat.util.times import humandelta  # noqa: PLC0415

    t1 = tm()
    async with (
        Dispatch(cfg, run=True) as dsp,
        dsp.sub_at(cfg.remote) as cfr,
    ):
        try:
            t2 = tm()
            cmd = cfr.sub_at(path)
            if parts:
                from moat.micro.cmd.tree.dir import SubStore  # noqa: PLC0415

                res = await SubStore(cmd).get(*args, **val)
            else:
                res = await cmd(*args, **val)
        except RemoteError as err:
            t3 = tm()
            yprint(dict(e=str(err.args[0])), stream=obj.stdout)
        else:
            t3 = tm()
            if isinstance(res, Msg):
                res = [res.args, res.kw]
            yprint(res, stream=obj.stdout)
    if time:
        print(f"{humandelta(t3 - t2)} (setup {humandelta(t2 - t1)})")


@cli.command(short_help="Read a console")
@click.pass_obj
@click.argument("path", nargs=1, type=P)
@catch_errors
async def cons(obj, path):
    """
    Read a Moat console.

    The command repeatedly calls the "crd" function on the given path and
    streams the result.
    """
    cfg = obj.mcfg
    async with (
        Dispatch(cfg, run=True) as dsp,
        dsp.sub_at(cfg.remote) as cfr,
    ):
        crd = cfr.sub_at(path).crd
        while True:
            try:
                res = await crd()
            except RemoteError as err:
                print(f"\nERR: {err!r}\n")
            else:
                print(res.decode("utf-8", errors="replace"), end="")


@cli.command("cfg", short_help="Get / Update the configuration")
@click.pass_obj
@click.option("-r", "--read", type=click.File("r"), help="Read config from this file")
@click.option("-R", "--read-client", help="Read config file from the client")
@click.option("-w", "--write", type=click.File("w"), help="Write config to this file")
@click.option("--stdout", is_flag=True, hidden=True)
@click.option("-W", "--write-client", help="Write config file to the client")
@click.option("-S", "--sync", is_flag=True, help="Sync the client after writing")
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
    file (``-r PATH``), as CBOR from Flash (``-R xx.cfg``), or from the
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
    path "r.s.cfg_", and a ``fs.Cmd`` app at path "r.s.fs". You can change
    these paths with ``… cfg -P fs ‹path›`` and ``… cfg -P cfg ‹path›``.
    """
    if write and stdout:
        raise click.UsageError("no --stdout and --write")
    if stdout:
        write = obj.stdout

    if sync and (write or write_client):
        raise click.UsageError("You're not changing the running config!")

    cfg = obj.mcfg

    if read and write and not (read_client or write_client):
        # local file update: don't talk to the client
        if client or sync:
            raise click.UsageError("You're not talking to the client!")

        rcfg = yload(read)
        rcfg = process_args(rcfg, **attrs)
        yprint(rcfg, stream=write)
        return

    if read_client or write_client:
        from .path import MoatFSPath  # noqa: PLC0415

    p_cfg = cfg.path.get("cfg", P("cfg_"))
    p_fs = cfg.path.get("fs", P("fs"))
    async with (
        Dispatch(cfg, run=True, sig=True) as dsp,
        dsp.sub_at(cfg.remote) as cfr,
        cfr.cfg_at(p_cfg) as cf,
        cfr.sub_at(p_fs) as fs,
    ):
        has_attrs = any(a for a in attrs.values())
        codec = get_codec("std-cbor")

        if has_attrs and not (read or read_client or write or write_client):
            # No file access at all. Just update the client's RAM.

            val = process_args({}, **attrs)
            await cf.set(val, sync=sync)
            return

        if read:
            rcfg = yload(read)
        if read_client:
            p = MoatFSPath(read_client).connect_repl(fs)
            d = await p.read_bytes(chunk=64)
            if not read:
                rcfg = codec.decode(d)
            elif client:
                rcfg = merge(rcfg, codec.decode(d), replace=True)
            else:
                rcfg = merge(rcfg, codec.decode(d), replace=False)
        if not read and not read_client:
            rcfg = await cf.get()

        rcfg = process_args(rcfg, **attrs)
        if has_attrs and not write and not write_client:
            await cf.set(rcfg, sync=sync, replace=True)

        if write_client:
            if "apps" in rcfg:
                p = MoatFSPath(write_client).connect_repl(fs)
                d = codec.encode(rcfg)
                await p.write_bytes(d, chunk=64)
            else:
                print("No 'apps' section. Not writing.", file=sys.stderr)
        if write:
            yprint(rcfg, stream=write)
        elif not has_attrs and not write_client:
            yprint(rcfg, stream=obj.stdout)


@cli.command("run", short_help="Run the multiplexer")
@click.pass_obj
@catch_errors
async def run_(obj):
    """
    Run the MoaT stack.
    """
    async with Dispatch(obj.mcfg, run=True, sig=True):
        await idle()


@cli.command("mount")
@click.option("-b", "--blocksize", type=int, help="Max read/write message size", default=256)
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True), nargs=1)
@click.pass_obj
@catch_errors
async def mount_(obj, path, blocksize):
    """Mount a controller's file system on the host"""
    from moat.micro.fuse import wrap  # noqa: PLC0415

    cfg = obj.mcfg

    async with (
        Dispatch(cfg, run=True, sig=True) as dsp,
        dsp.sub_at(cfg.remote) as cfr,
        cfr.sub_at(cfg.path.fs) as sd,
        wrap(sd, path, blocksize=blocksize, debug=max(obj.debug - 1, 0)),
    ):
        if obj.debug:
            print("Mounted.")
        await idle()


@cli.command("rom")
@click.option("-d", "--device", type=int, help="ROMFS segment to use", default=0)
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True), nargs=1)
@click.pass_obj
@catch_errors
async def rom(obj, path, device):
    """Send a file system to the device's ROM"""
    path  # noqa:B018
    raise NotImplementedError

    cfg = obj.mcfg

    async with (
        Dispatch(cfg, run=True, sig=True) as dsp,
        dsp.sub_at(cfg.remote) as cfr,
        cfr.sub_at(cfg.path.rom) as sd,
    ):
        res = await sd.n()
        if device >= res:
            if res == 1:
                raise RuntimeError("Device has only one ROMFS.")
            elif not res:
                raise RuntimeError("Device does not have ROMFS.")
            raise RuntimeError("Device 0…{res-1} only.")

        _nblk, _blksz = await sd.stat()

        if obj.debug:
            print("Building ROMFS.")

        # TODO


@cli.command("path")
@click.pass_obj
@click.option("-m", "--manifest", is_flag=True, help="main manifest")
@catch_errors
async def path_(obj, manifest):
    """Path to the embedded system's files"""

    import pathlib  # noqa: PLC0415

    if manifest:
        import moat.micro._embed._tag as m  # noqa: PLC0415

        print(m.__file__.replace("_tag", "manifest"), file=obj.stdout)
        return

    import moat.micro._embed  # noqa: PLC0415

    for p in moat.micro._embed.__path__:  # noqa:SLF001
        p = pathlib.Path(p) / "lib"  # noqa:PLW2901
        if p.exists():
            print(p)
