#!/usr/bin/env python3
"""
Basic "modbus" tool: network client and server, serial client

"""

from __future__ import annotations

import logging  # pylint: disable=wrong-import-position
from getopt import getopt
from pprint import pprint

import asyncclick as click
import anyio

from .typemap import get_type, map_kind, map_type
from .types import InputRegisters, IntValue

log = logging.getLogger()


@click.group()
async def main():
    """Modbus client / server"""

    FORMAT = (
        "%(asctime)-15s %(threadName)-15s %(levelname)-8s %(module)-15s:%(lineno)-8s %(message)s"
    )
    logging.basicConfig(format=FORMAT)
    log.setLevel(logging.WARNING)


UNIT = 0x1


def _doc(v):
    return v.__doc__.split("\n")[0]


_args_kind = "\n".join(f"{k:3s}  {_doc(v)}" for k, v in map_kind.items())
_args_type = "\n".join(f"{k:3s}  {_doc(v)}" for k, v in map_type.items())
_args_help = f"""\
\b
Setting values:
-u UNIT   register to this unit; default 1
-k KIND   use this register range, default Input
-t TYPE   register this datatype, default Raw
-r REGNUM start at this register, default 0, auto-incremented
-n COUNT  register this many variables, default 1
-v VALUE  set the register(s) to this value

\b
Kinds:
{_args_kind}

\b
Types:
{_args_type}
"""


async def _server(host, port, debug, args):
    """
    Basic Modbus server, for static tests.
    """
    if debug:
        log.setLevel(logging.DEBUG)
    if not args:
        raise click.UsageError("You didn't add any values to serve")

    from moat.modbus.server import ModbusServer  # pylint: disable=import-outside-toplevel

    s = ModbusServer(address=host, port=port)
    unit = None
    kind = InputRegisters
    typ = IntValue
    num = 1
    reg = 0

    kv, a = getopt(
        args,
        "u:k:t:r:n:v:",
        "--unit= --kind= --type= reg= register= num= val= value=".split(),
    )
    if a:
        raise click.UsageError(f"Unknown argument: {' '.join(a)}")
    for k, v in kv:
        pend = True
        if k in ("-u", "--unit"):
            unit = s.add_unit(int(v))
        elif k in ("-k", "--kind"):
            kind = map_kind[v[0]]
        elif k in ("-t", "--type"):
            typ = get_type(v[0])
        elif k in ("-r", "--reg", "--register"):
            reg = int(v)
        elif k in ("-n", "--num"):
            num = int(v)
        elif k in ("-v", "--val", "--value"):
            try:
                v = int(v)
            except ValueError:
                v = float(v)
            if unit is None:
                unit = s.add_unit(1)
            for _ in range(num):
                unit.add(kind, reg, typ(v))
                reg += typ.len
            pend = False
        else:
            raise click.UsageError(f"Unknown argument: {k!r}")
    if pend:
        raise click.UsageError("Values must be at the end")

    await s.serve()


def mk_server(m):
    """Helper to create a server"""
    s = _server
    s = click.argument("args", nargs=-1, type=click.UNPROCESSED)(s)
    s = click.option("--debug", "-d", is_flag=True, help="Log debug messages")(s)
    s = click.option("--port", "-p", type=int, default=502, help="port to bind to")(s)
    s = click.option("--host", "-s", default="localhost", help="host to bind to")(s)
    s = m.command(
        "server",
        context_settings=dict(
            show_default=True,
            ignore_unknown_options=True,
            help_option_names=["-?", "--help"],
        ),
        epilog=_args_help,
    )(s)
    return s


server = mk_server(main)


def flint(v):
    """float-or-int"""
    try:
        return int(v)
    except ValueError:
        return float(v)


async def _client(host, port, unit, kind, start, num, type_, values, debug, interval, maxlen):
    """
    Basic Modbus-TCP client.
    """
    if debug:
        log.setLevel(logging.DEBUG)

    from moat.modbus.client import ModbusClient  # pylint: disable=import-outside-toplevel

    c = {}
    if maxlen:
        c["max_rd_len"] = maxlen
        c["max_wr_len"] = maxlen
    async with (
        ModbusClient() as g,
        g.host(host, port, **c) as h,
        h.unit(unit) as u,
        u.slot("default") as s,
    ):
        k = map_kind[kind[0]]
        t = get_type(type_)
        if values:
            if len(values) == 1:
                values = values * num
            elif num == 1:
                num = len(values)
            elif len(values) != num:
                raise click.UsageError("One or N values!")
        for i in range(num):
            v = s.add(k, start, t)
            if values:
                v.set(flint(values[i]), idem=False)
            start += t.len
            num -= 1

        last_res = None
        while True:
            if values:
                await s.setValues()  # pylint:disable=protected-access  ## TODO
            else:
                res = await s.getValues()  # pylint:disable=protected-access  ## TODO
                if last_res != res:
                    pprint(res)
                    last_res = res

            if interval:
                await anyio.sleep(interval)
            else:
                break


def mk_client(m):
    """helper to create a client"""
    c = _client
    c = click.argument("values", nargs=-1)(c)
    c = click.option("--debug", "-d", is_flag=True, help="Log debug messages")(c)
    c = click.option(
        "--type",
        "-t",
        "type_",
        default="raw",
        help="value type: raw, s1,u2,f4, c#/b#:text/bytes, x/X:bool/inv; Sx/Fx=swapped",
    )(c)
    c = click.option("--num", "-n", type=int, default=1, help="number of values")(c)
    c = click.option("--start", "-s", default=0, help="starting register")(c)
    c = click.option("--kind", "-k", default="i", help="query type: input, discrete, hold, coil")(
        c,
    )
    c = click.option("--unit", "-u", type=int, default=1, help="unit to query")(c)
    c = click.option("--port", "-p", type=int, default=502, help="destination port")(c)
    c = click.option("--host", "-h", default="localhost", help="destination host")(c)
    c = click.option("--interval", "-i", type=float, help="loop: read/write every N seconds")(c)
    c = click.option(
        "--max-len",
        "-L",
        "maxlen",
        type=int,
        default=30,
        help="max. modbus words per packet",
    )(c)
    c = m.command("client", context_settings=dict(show_default=True))(c)
    return c


client = mk_client(main)


async def _serclient(
    port,
    baudrate,
    stopbits,
    parity,
    unit,
    kind,
    start,
    num,
    type_,
    values,
    debug,
    maxlen,
):
    """
    Basic Modbus-RTU client.
    """
    if debug:
        log.setLevel(logging.DEBUG)

    from moat.modbus.client import ModbusClient  # pylint: disable=import-outside-toplevel

    c = {}
    if maxlen:
        c["max_rd_len"] = maxlen
        c["max_wr_len"] = maxlen
    async with (
        ModbusClient() as g,
        g.serial(port=port, baudrate=baudrate, stopbits=stopbits, parity=parity, **c) as h,
        h.unit(unit) as u,
        u.slot("default") as s,
    ):
        k = map_kind[kind[0]]
        t = get_type(type_)
        if values:
            if len(values) == 1:
                values = values * num
            elif len(values) != num:
                raise click.UsageError("One or N values!")
        for i in range(num):
            v = s.add(k, start, t)
            if values:
                v.set(flint(values[i]))
            start += t.len
            num -= 1

        try:
            if values:
                await s.setValues()  # pylint:disable=protected-access  ## TODO
            else:
                res = await s.getValues()  # pylint:disable=protected-access  ## TODO
                pprint(res)
        except Exception as exc:  # pylint: disable=broad-except
            log.exception("Problem: %r", exc)


def add_serial_cfg(c):
    """Helper for serial port configuration"""
    c = click.option(
        "--port",
        "-p",
        required=True,
        type=str,
        help="destination port (/dev/ttyXXX)",
    )(c)
    c = click.option("--baudrate", "-b", type=int, default=9600, help="Baud rate (9600)")(c)
    c = click.option("--parity", "-P", type=str, default="N", help="Parity (NEO), default N")(c)
    c = click.option("--stopbits", "-S", type=int, default=1, help="Stopbits (12), default 1")(c)
    return c


def mk_serial_client(m):
    """helper to create a sserial client"""
    c = _serclient
    c = click.argument("values", nargs=-1)(c)
    c = click.option("--debug", "-d", is_flag=True, help="Log debug messages")(c)
    c = click.option(
        "--type",
        "-t",
        "type_",
        default="raw",
        help="value type: s1,s2,s4,u1,u2,u4,f2,f4,raw; Sx/Fx=swapped",
    )(c)
    c = click.option("--num", "-n", type=int, default=1, help="number of values")(c)
    c = click.option("--start", "-s", default=0, help="starting register")(c)
    c = click.option("--kind", "-k", default="i", help="query type: input, discrete, hold, coil")(
        c,
    )
    c = add_serial_cfg(c)
    c = click.option("--unit", "-u", type=int, default=1, help="unit to query")(c)
    c = click.option(
        "--max-len",
        "-L",
        "maxlen",
        type=int,
        default=30,
        help="max. modbus words per packet",
    )(c)
    c = m.command("serial", context_settings=dict(show_default=True))(c)
    return c


serialclient = mk_serial_client(main)


if __name__ == "__main__":
    main(_anyio_backend="trio")  # pylint: disable=unexpected-keyword-arg
