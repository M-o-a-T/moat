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
    process_args,
    to_attrdict,
    yload,
    yprint,
)
from moat.micro.cmd.tree.dir import Dispatch
from moat.micro.cmd.util.part import get_part
from moat.lib.codec.errors import NoPathError, RemoteError
from moat.lib.cmd.msg import Msg
from moat.micro.stacks.util import TEST_MAGIC
from moat.util.compat import idle
from moat.util.main import load_subgroup
from moat.lib.codec import get_codec

import asyncclick as click

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
            if type(e) in skip_exc:
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
    ocfg = cfg = obj.cfg["micro"]

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
            raise click.UsageError("Use '--section' to specify which remote to set up.")
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
        pth[k] = cfg.remote + v

    obj.mcfg = to_attrdict(cfg)


@cli.command(name="setup", short_help="Copy MoaT to MicroPython")
@click.pass_context
@click.option("-i", "--install", is_flag=True, help="Install MicroPython")
@click.option("-r", "--run", is_flag=True, help="Run MoaT after updating")
@click.option("-F", "--rom", is_flag=True, help="Upload to ROM Flash")
@click.option("--run-section", type=str, help="Section with runtime config (default: 'run')")
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
async def setup_(ctx, run_section=None, **kw):
    """
    Initial sync of MoaT code to a MicroPython device.

    MoaT must not currently run on the target. If it does,
    send `` TBD `` commmands.
    """
    from .setup import setup

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
    if run is True:
        st["run"] = ctx.obj.cfg.micro[run_section or "run"]
    elif isinstance(run, str):
        st["run"] = ctx.obj.cfg.micro[run]

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
    Sync of MoaT code on a running MicroPython device.

    """
    from .path import MoatFSPath
    from .setup import do_update, do_copy

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
            dsp.sub_at(cfg.path.fs) as rfs,
            dsp.sub_at(cfg.path.sys) as rsys,
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
    cfg = obj.cfg
    async with Dispatch(cfg) as dsp, dsp.sub_at(cfg.path.sys) as sd:
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
        print("Success:", res, file=sys.stderr)


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
    Use `-s _a:n XXX` to append to it.
    """
    cfg = obj.mcfg
    val = {"_a": []}
    val = process_args(val, no_path=True, **attrs)
    args = val.pop("_a", ())
    logger.debug(
        "Command: %s %s %s",
        cfg.remote + path,
        "-" if not args else " ".join(str(a) for a in args),
        "-" if not val else " ".join(f"{k}={v!r}" for k, v in val.items()),
    )

    async with Dispatch(cfg, run=True) as dsp, dsp.sub_at(cfg.remote) as sd:
        try:
            res = await sd.sub_at(path)(*args, **val)
        except RemoteError as err:
            yprint(dict(e=str(err.args[0])), stream=obj.stdout)
        else:
            if isinstance(res, Msg):
                res = [msg.args, msg.kw]
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
        from .path import MoatFSPath

    async with (
        Dispatch(cfg, run=True, sig=True) as dsp,
        dsp.cfg_at(cfg.path.cfg) as cf,
        dsp.sub_at(cfg.path.fs) as fs,
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
        if not write:
            if "apps" not in rcfg:
                raise click.UsageError("No 'apps' section.")
            if not write_client:
                await cf.set(rcfg, sync=sync, replace=True)

        if write_client:
            p = MoatFSPath(write_client).connect_repl(fs)
            d = codec.encode(rcfg)
            await p.write_bytes(d, chunk=64)
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


@cli.command("rom")
@click.option("-d", "--device", type=int, help="ROMFS segment to use", default=0)
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True), nargs=1)
@click.pass_obj
@catch_errors
async def rom(obj, path, device):
    """Send a file system to the device's ROM"""
    cfg = obj.mcfg

    async with (
        Dispatch(cfg, run=True, sig=True) as dsp,
        dsp.sub_at(cfg.path.rom) as sd,
    ):
        res = await sd.n()
        if device >= res:
            if res == 1:
                raise RuntimeError("Device has only one ROMFS.")
            elif not res:
                raise RuntimeError("Device does not have ROMFS.")
            raise RuntimeError("Device 0…{res-1} only.")

        nblk,blksz = await sd.stat()

        if obj.debug:
            print("Building ROMFS.")


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
