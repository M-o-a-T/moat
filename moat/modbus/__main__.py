#!/usr/bin/env python3
"""
Basic tool support

"""
from getopt import getopt
from functools import partial
from .typemap import get_type, get_kind, map_kind, map_type

import asyncclick as click

import logging  # pylint: disable=wrong-import-position
log = logging.getLogger()


@click.group()
async def main():
    """Modbus client / server"""

    FORMAT = "%(asctime)-15s %(threadName)-15s %(levelname)-8s %(module)-15s:%(lineno)-8s %(message)s"
    logging.basicConfig(format=FORMAT)
    log.setLevel(logging.WARN)

    pass  # pylint: disable=unnecessary-pass


UNIT = 0x1


def _doc(v):
    return v.__doc__.split("\n")[0]


_args_kind = "\n".join(f"{k :3s}  {_doc(v)}" for k, v in map_kind.items())
_args_type = "\n".join(f"{k :3s}  {_doc(v)}" for k, v in map_type.items())
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
        click.UsageError("You didn't add any values to serve")

    from moat.modbus.server import ModbusServer  # pylint: disable=import-outside-toplevel

    s = ModbusServer(address=host, port=port)
    unit = None
    kind = InputRegisters
    typ = IntValue
    num = 1
    reg = 0

    kv, a = getopt(
        args, "u:k:t:r:n:v:", "--unit= --kind= --type= reg= register= num= val= value=".split()
    )
    if a:
        raise click.UsageError(f"Unknown argument: {' ' .join(a)}")
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
                unit = s.add_unit(int(1))
            for _ in range(num):
                unit.add(kind, reg, typ(v))
                reg += typ.len
            pend = False
        else:
            raise click.UsageError(f"Unknown argument: {k !r}")
    if pend:
        raise click.UsageError("Values must be at the end")

    await s.serve()

def mk_server(m):
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


async def _client(host, port, unit, kind, start, num, type_, values, debug):
    """
    Basic Modbus-TCP client.
    """
    if debug:
        log.setLevel(logging.DEBUG)

    from moat.modbus.client import ModbusClient  # pylint: disable=import-outside-toplevel

    async with ModbusClient() as g:
        h = g.host(host, port)
        u = h.unit(unit)
        s = u.slot("default")

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
                v.value = flint(values[i])
            start += t.len
            num -= 1

        try:
            if values:
                await s.setValues()
            else:
                res = await s.getValues()
                print(res)
        except Exception as exc:  # pylint: disable=broad-except
            log.exception("Problem: %r", exc)

def mk_client(m):
    c = _client
    c = click.argument("values", nargs=-1)(c)
    c = click.option("--debug", "-d", is_flag=True, help="Log debug messages")(c)
    c = click.option( "--type", "-t", "type_", default="raw", help="value type: s1,s2,s4,u1,u2,u4,f2,f4,raw; Sx/Fx=swapped",)(c)
    c = click.option("--num", "-n", type=int, default=1, help="number of values")(c)
    c = click.option("--start", "-s", default=0, help="starting register")(c)
    c = click.option("--kind", "-k", default="i", help="query type: input, discrete, hold, coil")(c)
    c = click.option("--unit", "-u", type=int, default=1, help="unit to query")(c)
    c = click.option("--port", "-p", type=int, default=502, help="destination port")(c)
    c = click.option("--host", "-h", default="localhost", help="destination host")(c)
    c = m.command("client", context_settings=dict(show_default=True))(c)
    return c

client = mk_client(main)


if __name__ == "__main__":
    main(_anyio_backend="trio")  # pylint: disable=unexpected-keyword-arg
