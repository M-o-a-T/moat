"""
Basic "moat modbus" tool: network client and server, serial client
"""

import sys
import asyncclick as click
import anyio

from moat.util import load_subgroup
from moat.modbus.client import ModbusClient

from .__main__ import mk_client, mk_serial_client, mk_server, add_serial_cfg


@load_subgroup(sub_pre="moat.modbus")
async def cli():
    """Modbus tools"""
    pass


serialclient = mk_serial_client(cli)

client = mk_client(cli)
server = mk_server(cli)

@cli.group(invoke_without_command=True)
@add_serial_cfg
@click.pass_context
async def relay(ctx, **params):
    """
    A basic Modbus RTU monitoe.
    """
    obj = ctx.obj

    if ctx.invoked_subcommand is not None:
        obj.A = params
        return

    async def mon(msg):
        print(msg)

    async with ModbusClient() as g, g.serial(monitor=mon, **params) as h:
        if obj.debug > 1:
            print("Listening.", file=sys.stderr)
        while True:
            await anyio.sleep(99999)

@relay.command
@add_serial_cfg
@click.option("-r","--retry", type=int, help="Delay between restarts in case of errors")
@click.pass_obj
async def to(obj, retry, **params):
    """
    Modbus relaying between two RTU devices.

    Useful for monitoring, reverse engineering, speed translation, debugging …
    """
    A = None
    B = None
    n_A = 0
    n_B = 0

    async def mon_A(msg):
        print("A:",msg)
        await B.send(msg)

        nonlocal n_A
        n_A += 1

    async def mon_B(msg):
        print("B:",msg)
        await A.send(msg)

        nonlocal n_B
        n_B += 1

    while True:
        n_A = 0
        n_B = 0
        try:
            async with ModbusClient() as g_a, g_a.serial(monitor=mon_A,**obj.A) as A, \
                    ModbusClient() as g_b, g_b.serial(monitor=mon_B,**params) as B:
                while True:
                    await anyio.sleep(99999)
        except Exception as exc:
            if not retry or not n_A or not n_B:
                raise
            print_exc(file=sys.stderr)
            print(f"Retrying in {retry}s", file=sys.stderr)
            await anyio.sleep(retry)
