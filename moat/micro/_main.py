"""
Command-line code for moat.micro
"""

# pylint: disable=import-outside-toplevel

import logging
import os
import sys
from contextlib import asynccontextmanager

import anyio
import asyncclick as click
from moat.util import (
    P,
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
from moat.util.main import load_subgroup

from .compat import TaskGroup, idle
from .direct import DirectREPL

logger = logging.getLogger(__name__)


def _clean_cfg(cfg):
    # cfg = attrdict(apps=cfg["apps"])  # drop all the other stuff
    return cfg


@load_subgroup(prefix="moat.micro")
@click.pass_obj
@click.option(
    "-c",
    "--config",
    help="Configuration file (YAML)",
    type=click.Path(dir_okay=False, readable=True),
)
@click.option(
    "-s",
    "--socket",
    help="Socket to use / listen to when multiplexing (cfg.connect.unix.port)",
    type=click.Path(dir_okay=False, writable=True, readable=True),
)
@click.option(
    "-p",
    "--port",
    help="Port your µPy device is connected to (cfg.setup.serial.port)",
    type=click.Path(dir_okay=False, writable=True, readable=True, exists=True),
)
@click.option(
    "-b", "--baudrate", type=int, default=115200, help="Baud rate to use (cfg.setup.serial.rate)"
)
async def cli(obj, socket, port, baudrate, config):
    """MicroPython satellites"""
    cfg = obj.cfg.micro

    if config:
        with open(config, "r") as f:
            cc = yload(f)
            merge(cfg, cc)
    if socket:
        if not os.path.isabs(socket):
            socket = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), socket)
        cf = cfg.setdefault("connect", {})
        cf.setdefault("mode","unix")
        cf.setdefault("unix",{})["port"] = socket
    if port or baudrate:
        cf = cfg.setdefault("setup", {})
        cf.setdefault("mode","serial")
        cf = cf.setdefault("serial",{})
        if port:
            cf["port"]= port
        if baudrate:
            cf.setdefault("mode", {})["rate"]= baudrate

    obj.cfg = to_attrdict(cfg)


@cli.command(short_help='Copy MoaT to MicroPython')
@click.pass_obj
@click.option("-n", "--no-run", is_flag=True, help="Don't run MoaT after updating")
@click.option("-N", "--no-reset", is_flag=True, help="Don't reboot after updating")
@click.option(
    "-s",
    "--source",
    type=click.Path(dir_okay=True, file_okay=True, path_type=anyio.Path),
    help="Files to sync",
)
@click.option("-d", "--dest", type=str, default="", help="Destination path")
@click.option("-R", "--root", type=str, default="/", help="Destination root")
@click.option("-S", "--state", type=str, help="State to enter")
@click.option("-f", "--force-exit", is_flag=True, help="Halt via an error packet")
@click.option("-e", "--exit", "exit_", is_flag=True, help="Halt using an exit message")
@click.option("-c", "--config", type=click.File("rb"), help="Config file to copy over")
@click.option("-L", "--link", type=str, help="Link name to use, if ambiguous")
@click.option("-v", "--verbose", is_flag=True, help="Use verbose mode on the target")
@click.option(
    "-m", "--mplex", "--multiplex", is_flag=True, help="Run the multiplexer after syncing"
)
@click.option("-M", "--mark", type=int, help="Serial marker", hidden=True)
@click.option("-C", "--cross", help="path to mpy-cross")
async def setup(
    obj,
    source,
    root,
    dest,
    no_run,
    no_reset,
    force_exit,
    exit_,
    verbose,
    link,
    state,
    config,
    mplex,
    cross,
    mark,
):
    """
    Initial sync of MoaT code to a MicroPython device.

    If MoaT is already running on the target and "sync" doesn't work,
    you can use "-e" or "-f" to stop it.
    """
    cfg = obj.cfg
    links = []
    for k,v in cfg.apps.items():
        if v == "serial.Link":
            links.append(k)
    if link:
        lcfg = obj.cfg[link]
    elif cfg.setup.mode == "serial":
        lcfg = cfg.setup.serial
    elif len(k) == 1:
        lcfg = cfg[k[0]]
    elif k:
        raise click.UsageError(f"Multiple serial apps ({','.join(k)}) found in the config.")
    else:
        raise click.UsageError(f"No serial apps found in the config.")

    except KeyError as exc:
        raise click.UsageError(f"No data for {exc} found in the config.")

    if mark:
        lcfg.mode.mark = mark

    if no_run and verbose:
        raise click.UsageError("You can't not-start the target in verbose mode")
    # 	if not source:
    # 		source = anyio.Path(__file__).parent / "_embed"

    from .main import ABytes, copy_over, get_link_serial, get_serial
    from .path import MoatDevPath

    async with get_serial(lcfg) as ser:
        if force_exit or exit_:
            if force_exit:
                if lcfg.mode.guarded:
                    pk = b"\xc1\xc1"
                else:
                    pk = b"\xc1"
            else:
                pk = packer(dict(a=["sys", "stop"], code="SysStoP"))
                if lcfg.guarded:
                    pk = b"\xc1" + pk

            if obj.mode.reliable:
                from serialpacker import SerialPacker  # pylint:disable=import-error

                spc = {}
                if lcfg.mode.mark is not None:
                    spc["mark"] = lcfg.mode.mark
                elif lcfg.mode.guarded:
                    spc["mark"] = 0xc1
                sp = SerialPacker(**spc)
                h, pk, t = sp.frame(pk)
                pk = h + pk + t

            await ser.send(pk)
            logger.debug("Sent takedown: %r", pk)
            while True:
                m = None
                with anyio.move_on_after(0.2):
                    m = await ser.receive()
                    logger.debug("IN %r", m)
                if m is None:
                    break

        async with DirectREPL(ser) as repl:
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
                await repl.exec(f"f=open('moat.state','w'); f.write({state!r}); f.close()")
            if config:
                cfg = yload(config)
                cfg = _clean_cfg(cfg)
                cfg = packer(cfg)
                f = ABytes("moat.cfg", cfg)
                await copy_over(f, MoatDevPath("moat.cfg").connect_repl(repl), cross=cross)

            if no_reset:
                return

            await repl.soft_reset(run_main=False)
            if no_run:
                return

            o, e = await repl.exec_raw(
                f"from main import go_moat; go_moat(state='once',log={verbose !r})", timeout=30
            )
            if o:
                print(o)
            if e:
                print("ERROR", file=sys.stderr)
                print(e, file=sys.stderr)
                sys.exit(1)

        async with get_link_serial(obj, ser) as req:
            res = await req.send(["sys", "test"])
            assert res == b"a\x0db\x0ac", res

            res = await req.send("ping", "pong")
            if res != "R:pong":
                raise RuntimeError("wrong reply")
            print("Success:", res)

    if mplex:
        await _mplex(obj)


@cli.command("sync", short_help='Sync MoaT code')
@click.pass_obj
@click.option(
    "-s",
    "--source",
    type=click.Path(dir_okay=True, file_okay=True, path_type=anyio.Path),
    required=True,
    help="Files to sync",
)
@click.option("-d", "--dest", type=str, required=True, default="", help="Destination path")
@click.option("-C", "--cross", help="path to mpy-cross")
async def sync_(obj, source, dest, cross):
    """
    Sync of MoaT code on a running MicroPython device.

    """
    from .main import copy_over, get_link
    from .path import MoatFSPath

    async with get_link(obj) as req:
        dst = MoatFSPath("/" + dest).connect_repl(req)
        await copy_over(source, dst, cross=cross)


@cli.command(short_help='Reboot MoaT node')
@click.pass_obj
@click.option("-S", "--state", help="State after reboot")
async def boot(obj, state):
    """
    Restart a MoaT node

    """
    from .main import get_link

    async with get_link(obj) as req:
        if state:
            await req.send(["sys", "state"], state=state)

        # reboot via the multiplexer
        logger.info("Rebooting target.")
        await req.send(["mplex", "boot"])

        # await t.send(["sys","boot"], code="SysBooT")
        await anyio.sleep(2)

        res = await req.request.send(["sys", "test"])
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
