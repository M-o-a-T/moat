"""
Command-line code for moat.micro
"""

# pylint: disable=import-outside-toplevel

import logging
import os
import sys

import anyio
import asyncclick as click
from moat.util import (
    P, Path,
    as_service,
    attr_args,
    attrdict,
    to_attrdict,
    merge,
    packer,
    process_args,
    unpacker,
    yload,
    yprint,
)
from moat.micro.proto.stream import RemoteBufAnyio
from moat.util.main import load_subgroup
from moat.micro.util import run_update

from .compat import TaskGroup, idle
from .direct import DirectREPL

logger = logging.getLogger(__name__)


def _clean_cfg(cfg):
    # cfg = attrdict(apps=cfg["apps"])  # drop all the other stuff
    return cfg

def _get(d,p):
    for pp in p:
        d = d[pp]
    return d

@load_subgroup(prefix="moat.micro", epilog="""
        The 'section' parameter says which part of the configuration to use.
        for connecting to the remote system. The defaults are:

        \b
        Command  Section
        =======  =======
        run      :          the config file's root
        setup    setup
        *        connect    used for all other commands

        The 'link' parameter specifies which app is the actual link.
        It defaults to 'r'.

        Paths('P') are a shorthand notation for lists. See 'moat util path'
        for details.
        """)
@click.pass_context
@click.option(
    "-c",
    "--config",
    help="Configuration file (YAML)",
    type=click.Path(dir_okay=False, readable=True),
)
@click.option("-S", "--section", type=P, help="Section to use")
@click.option("-L", "--link", type=P, help="path to the link")
@attr_args
async def cli(ctx, config, vars_, eval_, path_, section, link):
    """Run MicroPython satellites

    'moat micro' configures MoaT satellites and runs the link to them,
    as well as applications using it."""
    obj = ctx.obj
    cfg = obj.cfg.micro
    inv = ctx.invoked_subcommand
    if section is None:
        if inv == "setup":
            section = Path("setup")
        elif inv == "run":
            section = Path()
        else:
            section = Path("connect")
    cfg = _get(cfg, section)

    if config:
        with open(config, "r") as f:
            cc = yload(f)
            merge(cfg, cc)
    cfg = process_args(cfg, vars_, eval_, path_)
    if "apps" not in cfg:
        raise ValueError(f"Config at {section} requires 'apps' section")

    if inv != "run":
        if link is None:
            link = Path("r")
        cfg["path"] = link
    elif link is not None:
        raise click.UsageError("You can't use a link path with 'moat micro run'")


    obj.cfg = to_attrdict(cfg)


@cli.command(name="setup", short_help='Copy MoaT to MicroPython')
@click.pass_obj
@click.option("-r", "--run", is_flag=True, help="Run MoaT after updating")
@click.option("-N", "--reset", is_flag=True, help="Reboot after updating")
@click.option(
    "-S",
    "--source",
    type=click.Path(dir_okay=True, file_okay=True, path_type=anyio.Path),
    help="Files to sync",
)
@click.option("-D", "--dest", type=str, default="", help="Destination path")
@click.option("-R", "--root", type=str, default="/", help="Destination root")
@click.option("-U", "--update", is_flag=True, help="Run standard updates")
@click.option("-M", "--mount", type=click.Path(dir_okay=True, file_okay=False), help="Mount point for FUSE mount")
@click.option("-s", "--state", type=str, help="State to enter by default")
@click.option("-c", "--config", type=P, help="Config part to use for the device")
@click.option("-w", "--watch", is_flag=True, help="monitor the target's output after setup")
@click.option("-C", "--cross", help="path to mpy-cross")
async def setup_(obj, **kw):
    cfg = obj.cfg
    st = cfg.setdefault("args", {})
    for k,v in kw.items():
        if k not in st or v is not None:
            st[k] = v
    return await setup(obj,cfg,**st)

async def setup(
    obj,
    cfg, 
    source,
    root,
    dest,
    run,
    reset,
    state,
    config,
    cross,
    update,
    mount,
    watch,
):
    """
    Initial sync of MoaT code to a MicroPython device.

    MoaT must not currently run on the target.
    """
    # 	if not source:
    # 		source = anyio.Path(__file__).parent / "_embed"

    if watch and run:
        raise click.UsageError("You can't use 'watch' and 'run' at the same time")

    from .path import MoatDevPath, ABytes, copy_over
    from .cmd.tree import Dispatch,SubDispatch

    async with Dispatch(cfg, run=True) as dsp, \
            SubDispatch(dsp,cfg["path"]) as sd, \
            RemoteBufAnyio(sd) as ser, DirectREPL(ser) as repl:

        dst = MoatDevPath(root).connect_repl(repl)
        if source:
            if not dest:
                dest = str(source)
                pi = dest.find("/_embed/")
                if pi > 0:
                    dest = dest[pi + 8 :]
                    dst /= dest
            else:
                dst /= dest
            await copy_over(source, dst, cross=cross)
        if state:
            await repl.exec(f"f=open('moat.state','w'); f.write({state !r}); f.close()")
        if config:
            config = _clean_cfg(config)
            f = ABytes("moat.cfg", packer(config))
            await copy_over(f, MoatDevPath("moat.cfg").connect_repl(repl))

        if update:
            try:
                res = (await repl.exec(f"from moat.micro import _version as _v; print(_v.git); del _v")).strip()
            except ImportError:
                res = None
            await run_update(MoatDevPath(".").connect_repl(repl), res, cross=cross)
            # do not use "/". Running micropython tests locally requires
            # all satellite paths to be relative.

        if reset:
            await repl.soft_reset(run_main=run)
            # reset with run_main set should boot into MoaT

        if run:
            o, e = await repl.exec_raw(
                f"from main import go; go(state='once')", timeout=30
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


@cli.command("sync", short_help='Sync MoaT code')
@click.pass_obj
@click.option("-S", "--section", type=P, default=P("connect"), help="Setup section to use")
@click.option(
    "-s",
    "--source",
    type=click.Path(dir_okay=True, file_okay=True, path_type=anyio.Path),
    required=True,
    help="Files to sync",
)
@click.option("-d", "--dest", type=str, required=True, default="", help="Destination path")
@click.option("-C", "--cross", help="path to mpy-cross")
async def sync_(obj, source, dest, cross, section):
    """
    Sync of MoaT code on a running MicroPython device.

    """
    from .main import copy_over, get_link
    from .path import MoatFSPath

    cfg = _get(obj.cfg, section)
    async with Dispatch(cfg) as dsp, SubDispatch(dsp, cfg.get("path",P("r"))) as sd:
        dst = MoatFSPath("/" + dest).connect_repl(sd)
        await copy_over(source, dst, cross=cross)


@cli.command(short_help='Reboot MoaT node')
@click.pass_obj
@click.option("-s", "--state", help="State after reboot")
async def boot(obj, state):
    """
    Restart a MoaT node

    """
    cfg = _get(obj.cfg, section)
    async with Dispatch(cfg) as dsp, SubDispatch(dsp, cfg.get("path",P("r"))) as sd:
        if state:
            await sd.send("sys", "state", state=state)

        # reboot via the multiplexer
        logger.info("Rebooting target.")
        await req.send(["mplex", "boot"])

        # await t.send(["sys","boot"], code="SysBooT")
        await anyio.sleep(2)

        res = await req.request.send("sys", "test")
        assert res == b"a\x0db\x0ac", res

        res = await req.request.send("ping", "pong")
        if res != "R:pong":
            raise RuntimeError("wrong reply")
        print("Success:", res)


@cli.command(short_help='Send a MoaT command')
@click.pass_obj
@click.argument("path", nargs=1, type=P)
@attr_args(with_path=False, with_proxy=True)
async def cmd(obj, path, **attrs):
    """
    Send a MoaT command.

    """
    val = {}
    val = process_args(val, **attrs)
    if len(path) == 0:
        raise click.UsageError("Path cannot be empty")

    from .main import get_link
    from .proto.stack import RemoteError

    async with get_link(obj) as req:
        try:
            res = await req.send(list(path), val)
        except RemoteError as err:
            yprint(dict(e=str(err.args[0])))
        else:
            yprint(res)


@cli.command("cfg", short_help='Get / Update the configuration')
@click.pass_obj
@click.option("-r", "--read", type=click.File("r"), help="Read config from this file")
@click.option("-R", "--read-client", help="Read config file from the client")
@click.option("-w", "--write", type=click.File("w"), help="Write config to this file")
@click.option("-W", "--write-client", help="Write config file to the client")
@click.option("-s", "--sync", is_flag=True, help="Sync the client after writing")
@click.option(
    "-c", "--client", is_flag=True, help="The client's data win if both -r and -R are used"
)
@click.option("-u", "--update", is_flag=True, help="Don't replace the client config")
@attr_args(with_proxy=True)
async def cfg_(obj, read, read_client, write, write_client, sync, client, **attrs):
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
    or the client (no ``-w``/``-W`` argument).

    The client will not be updated if a ``-w``/``-W`` argument is present.
    If you want to update the client *and* write the config data to a file,
    simply do it in two steps.

    An "apps" section must be present if you write a complete configuration
    to the client.
    """
    if sync and (write or write_client):
        raise click.UsageError("You're not changing the running config!")

    from .main import get_link
    from .path import MoatFSPath

    if read and write and not (read_client or write_client):
        # local file update: don't talk to the client
        if client or sync:
            raise click.UsageError("You're not talking to the client!")

        cfg = yload(read)
        cfg = process_args(cfg, **attrs)
        yprint(cfg, stream=write)
        return

    async with get_link(obj) as req:
        has_attrs = any(a for a in attrs.values())

        if has_attrs and not (read or read_client or write or write_client):
            # No file access at all. Just update the client's RAM.
            val = merge(*attrs.values())  # pylint: disable=no-value-for-parameter
            await req.set_cfg(val, sync=sync)
            return

        if read:
            cfg = yload(read)
        if read_client:
            p = MoatFSPath(read_client).connect_repl(req)
            d = await p.read_bytes(chunk=64)
            if not read:
                cfg = unpacker(d)
            elif client:
                cfg = merge(cfg, unpacker(d), replace=True)
            else:
                cfg = merge(cfg, unpacker(d), replace=False)
        if not read and not read_client:
            cfg = await req.get_cfg()

        cfg = process_args(cfg, **attrs)
        if not write:
            if "apps" not in cfg:
                raise click.UsageError("No 'apps' section.")
            if not write_client:
                await req.set_cfg(cfg, sync=sync, replace=True)

        if write_client:
            p = MoatFSPath(write_client).connect_repl(req)
            d = packer(cfg)
            await p.write_bytes(d, chunk=64)
        if write:
            yprint(cfg, stream=write)


@cli.command("mplex", short_help='Run the multiplexer')
@click.option("-n", "--no-config", is_flag=True, help="don't fetch the config from the client")
@click.option("-r", "--remote", is_flag=True, help="talk via TCP")
@click.option("-S", "--server", help="talk to this system")
@click.argument("pipe", nargs=-1)
@click.pass_obj
async def mplex_(obj, **kw):
    "Multiplexer call"
    await _mplex(obj, **kw)


async def _mplex(obj, no_config=False, remote=False, server=None, pipe=None):
    """
    Run a multiplex channel to MoaT code on a running MicroPython device.

    If arguments are given, interpret as command to run as pipe to the
    device.
    """
    if not remote and not obj.port:
        raise click.UsageError("You need to specify a port")
    if not obj.socket:
        raise click.UsageError("You need to specify a socket")
    if server:
        remote = True
    elif remote:
        server = obj.cfg.micro.net.addr

    from .main import get_link_serial, get_remote, get_serial
    from .proto.multiplex import Multiplexer

    cfg_p = obj.cfg.micro.port
    if pipe:
        cfg_p.dev = pipe

    @asynccontextmanager
    async def stream_factory(req):
        # build a serial stream link
        if isinstance(cfg_p.get("dev", None), (list, tuple)):
            # array = program behind a pipe
            async with await anyio.open_process(cfg_p.dev, stderr=sys.stderr) as proc:
                ser = anyio.streams.stapled.StapledByteStream(proc.stdin, proc.stdout)
                async with get_link_serial(
                    obj, ser, request_factory=req, log=obj.debug > 3, lossy=False
                ) as link:
                    yield link
        else:
            async with get_serial(obj) as ser:
                async with get_link_serial(
                    obj, ser, request_factory=req, log=obj.debug > 3
                ) as link:
                    yield link

    @asynccontextmanager
    async def net_factory(req):
        # build a network connection link
        async with get_remote(obj, server, port=27587, request_factory=req) as link:
            yield link

    async def sig_handler(tg):
        import signal

        with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM, signal.SIGHUP) as signals:
            async for _ in signals:
                tg.cancel()
                break  # default handler on next

    async with TaskGroup() as tg:
        await tg.spawn(sig_handler, tg, _name="sig")
        obj.debug = False  # for as_service

        async with as_service(obj):
            mplex = Multiplexer(
                net_factory if remote else stream_factory,
                obj.socket,
                cfg=obj.cfg.micro,
                load_cfg=not no_config,
            )
            await mplex.serve()


@cli.command()
@click.option("-b", "--blocksize", type=int, help="Max read/write message size", default=256)
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True), nargs=1)
@click.pass_obj
async def mount(obj, path, blocksize):
    """Mount a controller's file system on the host"""
    from .main import get_link

    async with get_link(obj) as req:
        from moat.micro.fuse import wrap

        async with wrap(req, path, blocksize=blocksize, debug=obj.debug):
            await idle()
