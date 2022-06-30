#!/usr/bin/python3

import sys
import errno
import logging
import msgpack

import anyio
from anyio_serial import Serial
import asyncclick as click
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from moat.direct import DirectREPL
from moat.path import MoatDevPath, MoatFSPath, copytree
from moat.stacks import console_stack
from moat.compat import TaskGroup, UAStream
from moat.util import attrdict, as_service, P, attr_args, process_args, yprint
from moat.proto.multiplex import Multiplexer
from moat.proto import RemoteError
from moat.cmd import BaseCmd

def add_client_hooks(req):
    bc = req.stack(BaseCmd)
    bc.cmd_link = lambda _:0

async def copy_over(src, dst):
    tn = 0
    while (n := await copytree(src,dst)):
        tn += n
        if n == 1:
            logger.info("One file changed. Verifying.")
        else:
            logger.info(f"{n} files changed. Verifying.")
    logger.info("Done. No (more) differences detected.")
    return tn


@asynccontextmanager
async def get_serial(obj):
    """\
        Open the specified serial port.
        """
    _h={}
    try:
        _h['baudrate'] = obj.baudrate
    except AttributeError:
        pass
    ser = Serial(obj.port, **_h)
    async with ser:
        yield ser


@asynccontextmanager
async def get_link_serial(obj, ser, **kw):
    """\
        Link to the target using this serial port.
        """
    t,b = await console_stack(UAStream(ser), log=obj.verbose>2, reliable=not obj.reliable, console=0xc1 if obj.guarded else False, **kw)
    async with TaskGroup() as tg:
        task = await tg.spawn(b.run)
        try:
            yield t
        finally:
            task.cancel()


@asynccontextmanager
async def get_link(obj, **kw):
    """\
        Link to the target: the socket, if that can be connected to,
        or the serial port.
        """
    try:
        if obj.socket:
            sock = await anyio.connect_unix(obj.socket)
        else:
            raise AttributeError("socket")
    except (AttributeError,OSError):
        async with get_serial(obj) as ser:
            async with get_link_serial(obj,ser, **kw) as link:
                yield link
    else:
        try:
            t,b = await console_stack(UAStream(sock), log=obj.verbose>2, reliable=True, **kw)
            async with TaskGroup() as tg:
                task = await tg.spawn(b.run)
                yield t
                task.cancel()
        finally:
            await sock.aclose()


@click.group()
@click.pass_context
@click.option("-s","--socket", help="Socket to use / listen to when multiplexing", type=click.Path(dir_okay=False,writable=True,readable=True))
@click.option("-p","--port", help="Port your µPy device is connected to", type=click.Path(dir_okay=False,writable=True,readable=True,exists=True), default="/dev/ttyACM0")
@click.option("-b","--baudrate", type=int, default=115200, help="Baud rate to use")
@click.option("-v","--verbose", count=True, help="Be more verbose")
@click.option("-q","--quiet", count=True, help="Be less verbose")
@click.option("-R","--reliable", is_flag=True, help="Use Reliable mode, wrap messages in SerialPacker frame")
@click.option("-g","--guarded", is_flag=True, help="Use Guard mode (prefix msgpack with 0xc1 byte)")
async def main(ctx, socket,port,baudrate,verbose,quiet,reliable,guarded):
    ctx.ensure_object(attrdict)
    obj=ctx.obj

    obj.verbose = verbose+1-quiet
    logging.basicConfig(level=logging.DEBUG if obj.verbose>2 else logging.INFO if obj.verbose>1 else logging.WARNING if obj.verbose>0 else logging.ERROR)

    obj.socket=socket
    obj.port=port
    if baudrate:
        obj.baudrate=baudrate
    if reliable and guarded:
        raise click.UsageError("Reliable and Guarded mode don't like each other")
    obj.reliable=reliable
    obj.guarded=guarded


@main.command(short_help='Copy MoaT to MicroPython')
@click.pass_obj
@click.option("-n","--no-run", is_flag=True, help="Don't run MoaT after updating")
@click.option("-N","--no-reset", is_flag=True, help="Don't reboot after updating")
@click.option("-s","--source", type=click.Path(dir_okay=True,file_okay=False,path_type=anyio.Path), help="Files to sync")
@click.option("-S","--state", type=str, help="State to enter")
@click.option("-f","--force-exit", is_flag=True, help="Halt via an error packet")
@click.option("-e","--exit", is_flag=True, help="Halt using an exit message")
@click.option("-v","--verbose", is_flag=True, help="Use verbose mode on the target")
async def setup(obj, source, no_run, no_reset, force_exit, exit, verbose, state):
    """
    Initial sync of MoaT code to a MicroPython device.

    If MoaT is already running on the target and "sync" doesn't work, 
    you can use "-e" or "-f" to stop it.
    """
    if not obj.port:
        raise click.UsageError("You need to specify a port")
    if no_run and verbose:
        raise click.UsageError("You can't not-start the target in verbose mode")

    async with get_serial(obj) as ser:

        if force_exit or exit:
            if force_exit:
                pk = b"\xc1\xc1"
            else:
                pk = msgpack.Packer().packb(dict(a=["sys","stop"],code="SysStoP"))
                pk = pk+b"\xc1"+pk

            if obj.reliable:
                from serialpacker import SerialPacker
                sp=SerialPacker()
                h,t = sp.frame(pk)
                pk = h+pk+t

            await ser.send(pk)
            logger.debug("Sent takedown: %r",pk)
            while True:
                m = None
                with anyio.move_on_after(0.2):
                    m = await ser.receive()
                    logger.debug("IN %r",m)
                if m is None:
                    break

        async with DirectREPL(ser) as repl:
            dst = MoatDevPath("/").connect_repl(repl)
            if source:
                await copy_over(source, dst)
            if state:
                await repl.exec(f"f=open('moat.state','w'); f.write({state!r}); f.close()")
            if no_reset:
                return

            await repl.soft_reset(run_main=False)
            if no_run:
                return

            o,e = await repl.exec_raw(f"import main; main.go_moat(log={verbose !r})", timeout=30)
            if o:
                print(o)
            if e:
                print("ERROR", file=sys.stderr)
                print(e, file=sys.stderr)
                sys.exit(1)

        async with get_link_serial(obj, ser) as req:
            res = await req.send(["sys","test"])
            assert res == b"a\x0db\x0ac", res

            res = await req.send("ping","pong")
            if res != "R:pong":
                raise RuntimeError("wrong reply")
            print("Success:", res)

            
@main.command(short_help='Sync MoaT code')
@click.pass_obj
@click.option("-s","--source", type=click.Path(dir_okay=True,file_okay=False,path_type=anyio.Path), required=True, help="Files to sync")
async def sync(obj, source):
    """
    Sync of MoaT code on a running MicroPython device.

    """
    if not obj.port:
        raise click.UsageError("You need to specify a port")

    async with get_link(obj) as req:
        add_client_hooks(req)

        dst = MoatFSPath("/").connect_repl(req)
        await copy_over(source, dst)

            
@main.command(short_help='Reboot MoaT node')
@click.pass_obj
#@click.option("-n","--no-run", is_flag=True, help="Don't reboot / run MoaT after updating")
async def boot(obj):
    """
    Reset a MoaT node

    """
    if not obj.port:
        raise click.UsageError("You need to specify a port")

    async with get_link(obj) as req:
        add_client_hooks(req)

        # reboot via the multiplexer
        logger.info("Files updated. Rebooting target.")
        await req.send(["mplex","boot"])

        #await t.send(["sys","boot"], code="SysBooT")
        await anyio.sleep(2)

        res = await req.request.send(["sys","test"])
        assert res == b"a\x0db\x0ac", res

        res = await req.request.send("ping","pong")
        if res != "R:pong":
            raise RuntimeError("wrong reply")
        print("Success:", res)

            
@main.command(short_help='Send a MoaT command')
@click.pass_obj
@click.argument("path", nargs=1, type=P)
@attr_args
async def cmd(obj, path, vars_,eval_,path_):
    """
    Send a MoaT command.

    """
    if not obj.port:
        raise click.UsageError("You need to specify a port")

    val = {}
    val = process_args(val, vars_,eval_,path_)

    async with get_link(obj) as req:
        add_client_hooks(req)

        try:
            res = await req.send(list(path), val)
        except RemoteError as err:
            yprint(dict(e=str(err.args[0])))
        else:
            yprint(res)

            
@main.command(short_help='Run the multiplexer')
@click.pass_obj
async def mplex(obj):
    """
    Sync of MoaT code on a running MicroPython device.

    """
    if not obj.port:
        raise click.UsageError("You need to specify a port")
    if not obj.socket:
        raise click.UsageError("You need to specify a socket")

    @asynccontextmanager
    async def stream_factory(req):
        async with get_serial(obj) as ser:
            async with get_link_serial(obj, ser, request_factory=req) as link:
                yield link

    async def sig_handler(tg):
        import signal
        with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM, signal.SIGHUP) as signals:
            async for signum in signals:
                tg.cancel()
                break  # default handler on next

    async with TaskGroup() as tg:
        await tg.spawn(sig_handler, tg)
        obj.debug = False  # for as_service
        async with as_service(obj):
            mplex = Multiplexer(stream_factory, obj.socket)
            await mplex.serve()

            
if __name__ == "__main__":
    main(_anyio_backend="trio")

