"""
Basic "moat modbus" tool: network client and server, serial client
"""

import sys
import traceback

import anyio
import asyncclick as click
from moat.util import load_subgroup

from moat.modbus.client import ModbusClient
from moat.modbus.server import SerialModbusServer, RelayServer

from .__main__ import add_serial_cfg, mk_client, mk_serial_client, mk_server


@load_subgroup(sub_pre="moat.modbus")
async def cli():
    """Modbus tools"""
    pass


serialclient = mk_serial_client(cli)

client = mk_client(cli)
server = mk_server(cli)


def print_exc(exc, **kw):  # pylint: disable=missing-function-docstring
    traceback.print_exception(type(exc), exc, exc.__traceback__, **kw)


@cli.group(invoke_without_command=True)
@add_serial_cfg
@click.pass_context
async def monitor(ctx, **params):
    """
    A basic Modbus RTU monitor.

    This command dumps the messages on a Modbus RTU line.

    The arguments address the link to the server, i.e. it acts as a Modbus client.
    You need to add a "to" subcommand with the connection that should act as
    the server, i.e. which the actual client is connected to.

    Otherwise this is TODO, as distinguishing client
    and server messages is somewhat nontrivial.

    """
    obj = ctx.obj

    if ctx.invoked_subcommand is not None:
        obj.A = params
        return

    raise click.UsageError("Single line monitoring is not implemented yet")

#   async def mon(msg):
#       print(msg)

#   async with ModbusClient() as g, g.serial(monitor=mon, **params) as h:
#       g, h  # pylint: disable=pointless-statement
#       if obj.debug > 1:
#           print("Listening.", file=sys.stderr)
#       while True:
#           await anyio.sleep(99999)


@monitor.command
@add_serial_cfg
@click.option("-r", "--retry", type=int, help="Delay between restarts in case of errors")
@click.pass_obj
async def to(obj, retry, **params):
    """
    This subcommand describes the ModBus interface with the client(s).

    Useful for reverse engineering, serial speed/format translation, debugging …
    """
    A = None
    B = None

    class Server(RelayServer, SerialModbusServer):
        def mon_request(self, request):
            print(f"> {request}")

        def mon_response(self, response):
            print(f"< {response}")

        pass

    while True:
        try:
            async with ModbusClient() as g_a, g_a.serial(**obj.A) as A, Server(client=A, **params) as B:
                await B.serve()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if not retry or not A or not B:
                raise
            print_exc(exc, file=sys.stderr)
            print(f"Retrying in {retry}s", file=sys.stderr)
            await anyio.sleep(retry)
