"""
Basic "moat modbus" tool: network client and server, serial client
"""

from __future__ import annotations

import sys
import traceback

import anyio
import asyncclick as click
from moat.util import load_subgroup

from moat.modbus.client import ModbusClient
from moat.modbus.server import RelayServer, SerialModbusServer

from pymodbus.pdu.register_message import WriteSingleRegisterRequest

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
@click.option("-t", "--timeout", type=float, default=0, help="Error if no more data (seconds)")
@click.option(
    "-T",
    "--initial-timeout",
    "timeout1",
    type=float,
    default=0,
    help="Error if no data (seconds)",
)
@click.pass_context
async def monitor(ctx, timeout, timeout1, **params):
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
        obj.timeout = timeout
        obj.timeout1 = timeout1
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
    This subcommand describes the ModBus interface of the client(s).

    Useful for reverse engineering, serial speed/format translation, debugging …
    """
    A = None
    B = None

    class Server(RelayServer, SerialModbusServer):
        """A time-out-ing serial Modbus relay"""

        def __init__(self, *a, **kw):
            self.__evt = anyio.Event()
            super().__init__(*a, **kw)

        def mon_request(self, request):
            "request monitor"
            if isinstance(request, WriteSingleRegisterRequest):
                print(f"> {request}", request.value)
            else:
                print(f"> {request}", getattr(request, "registers", ""))
            return request

        def mon_response(self, response):
            "response monitor"
            print(f"< {response}", getattr(response, "registers", ""))
            self.__evt.set()
            return response

        async def watch(self, t2, t1):
            "Timeout manager"
            t = t1
            while True:
                if t is None:
                    await self.__evt.wait()
                else:
                    with anyio.fail_after(t):
                        await self.__evt.wait()
                t = t2
                self.__evt = anyio.Event()

    while True:
        try:
            async with (
                ModbusClient() as g_a,
                g_a.serial(**obj.A) as A,
                Server(client=A, **params) as B,
                # anyio.create_task_group() as tg,
            ):
                await B.watch(obj.timeout, obj.timeout1)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if not retry or not A or not B:
                raise
            print_exc(exc, file=sys.stderr)
            print(f"Retrying in {retry}s", file=sys.stderr)
            await anyio.sleep(retry)
