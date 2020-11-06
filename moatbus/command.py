
import asyncclick as click
import logging
import random
import sys

@click.group()
@click.option("-v", "--verbose", count=True, help="Enable debugging. Use twice for more verbosity.")
@click.option("-q", "--quiet", count=True, help="Disable debugging. Opposite of '--verbose'.")
@click.pass_context
async def main(ctx, verbose, quiet):
    """
    This is the MoaTbus command interpreter. You need to add a subcommand
    for it to do anything.
    """
    ctx.ensure_object(dict)
    ctx.obj['debug'] = dbg = max(verbose - quiet + 1, 0)
    logging.basicConfig(level=[logging.ERROR,logging.WARNING,logging.DEBUG][min(2,dbg)])

    l = logging.getLogger("distmqtt.mqtt.protocol.handler")
    l.setLevel(logging.INFO)
    l = logging.getLogger("transitions.core")
    l.setLevel(logging.WARNING)


@main.command(
    short_help="Import the debugger", help="Imports PDB and then continues processing."
)
@click.argument("args", nargs=-1)
async def pdb(args):  # safe
    import pdb  # pylint: disable=redefined-outer-name

    pdb.set_trace()  # safe
    if not args:
        return
    return await main.main(args)

@main.command(short_help="Serial>MQTT gateway")
@click.option("-u","--uri", default='mqtt://localhost/', help="URI of MQTT server")
@click.option("-t","--topic", default='test/moat/bus', help="Topic to send incoming messages to")
@click.option("-i","--ident", help="Identifier for this gateway. Must be unique.")
@click.option("-P","--prefix", default='ser_', help="ID prefix. Used to prevent loops.")
@click.option("-p","--port", default='/dev/ttyUSB0', help="Serial port to access")
@click.option("-b","--baud", type=int, default=57600, help="Serial port baud rate")
@click.pass_obj
async def gateway(obj, uri,topic,ident,prefix,port,baud):
    if ident is None:
        ident = "".join(random.choices("abcdefghjkmnopqrstuvwxyz23456789", k=9))
    ident = prefix+ident

    from anyio_serial import Serial
    from moatbus.backend.stream import Anyio2TrioStream, StreamBusHandler
    from moatbus.backend.mqtt import MqttBusHandler
    from moatbus.server.gateway import Gateway

    async with MqttBusHandler(id=ident, uri=uri, topic=topic) as M:
        async with Serial(port=port, baudrate=baud) as S:
            S=Anyio2TrioStream(S)
            async with StreamBusHandler(S) as SB:
                gw = Gateway(SB, M, prefix)
                await gw.run()

@main.command(short_help="Address assignment processor")
@click.option("-u","--uri", default='mqtt://localhost/', help="URI of MQTT server")
@click.option("-t","--topic", default='test/moat/bus', help="Topic to send incoming messages to")
@click.option("-i","--ident", help="Identifier for this process. Must be unique.")
@click.option("-n","--node","id", type=int, default=1, help="Server number (1…3)")
@click.pass_obj
async def addr(obj, uri,topic,ident,id):
    if ident is None:
        ident = "".join(random.choices("abcdefghjkmnopqrstuvwxyz23456789", k=9))

    from moatbus.backend.mqtt import MqttBusHandler
    from moatbus.server.server import Server

    async with MqttBusHandler(id=ident, uri=uri, topic=topic) as M:
        async with Server(M, id=id) as S:
            async for upd in S:
                print(upd)

def cmd():
    """
    The main command entry point, as declared in ``setup.py``.
    """
    try:
        # pylint: disable=no-value-for-parameter,unexpected-keyword-arg
        main(standalone_mode=False)
    except click.exceptions.MissingParameter as exc:
        print(f"You need to provide an argument { exc.param.name.upper() !r}.\n", file=sys.stderr)
        print(exc.cmd.get_help(exc.ctx), file=sys.stderr)
        sys.exit(2)
    except click.exceptions.UsageError as exc:
        try:
            s = str(exc)
        except TypeError:
            logger.exception(repr(exc), exc_info=exc)
        else:
            print(s, file=sys.stderr)
        sys.exit(2)
    except click.exceptions.Abort:
        print("Aborted.", file=sys.stderr)
        pass
    except EnvironmentError:  # pylint: disable=try-except-raise
        raise
