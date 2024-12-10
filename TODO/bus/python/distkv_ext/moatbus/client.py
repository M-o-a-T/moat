# command line interface

import sys
import asyncclick as click
from collections.abc import Mapping
import importlib
import pkgutil
import time
import datetime

from distkv.util import yprint, attrdict, NotGiven, as_service, P, Path, path_eval, attr_args, process_args
from distkv.obj.command import std_command

from .model import MOATroot
from moatbus.message import BusMessage

@click.group(short_help="Manage MOAT devices.")
@click.pass_obj
async def cli(obj):
    """
    List MOAT devices, modify device handling …
    """
    obj.data = await MOATroot.as_handler(obj.client)
    await obj.data.wait_loaded()


@cli.command()
@click.argument("path", nargs=1)
@click.pass_obj
async def dump(obj, path):
    """Emit the current state as a YAML file."""
    res = {}
    path = P(path)

    async for r in obj.client.get_tree(
        obj.cfg.moatbus.prefix + path, nchain=obj.meta
    ):
        # pl = len(path) + len(r.path)
        rr = res
        if r.path:
            for rp in r.path:
                rr = rr.setdefault(rp, {})
        rr["_"] = r if obj.meta else r.value
    yprint(res, stream=obj.stdout)


cmd_bus = std_command(
    cli,
    "bus",
    aux=(
        click.option("-t", "--topic", type=P, help="MQTT topic for bus messages"),
    ),
    sub_name="bus",
    id_name=None,
    short_help="Manage MoaT buses"
)

@cli.command("type", short_help="list connection types/params")
@click.argument("type_", nargs=-1)
@click.pass_obj
def typ_(obj, type_):
    if not type_:
        type_=[]
        print("Known connection types:", file=obj.stdout)
        ext = importlib.import_module("moatbus.backend")
        for finder, name, ispkg in pkgutil.iter_modules(ext.__path__, ext.__name__ + "."):
            n = name.rsplit(".")[-1]
            if n[0] == '_':
                continue
            type_.append(n)

    table = []
    for mn in type_:
        from tabulate import tabulate

        m = importlib.import_module(f"moatbus.backend.{mn}")
        cnt = 0
        for n,x in m.Handler.PARAMS.items():
            if not cnt:
                table.append(("*",mn,m.Handler.short_help))
            t,i,c,d,m = x
            tn = "Path" if t is P else t.__name__
            table.append((n,tn,i))
            cnt += 1
        if not cnt:
            table.append(("*",mn,m.Handler.short_help+"(no params)"))

    if table:
        print(tabulate(table, tablefmt="plain", disable_numparse=True), file=obj.stdout)
    elif obj.verbose:
        print("No buses known.", file=sys.stderr)

@cmd_bus.command()
@click.pass_obj
async def monitor(obj):
    """Watch bus messages."""
    if obj.bus is None:
        raise click.BadParameterError(f"Bus {obj.n_bus !r} doesn't exist")
    async with obj.client.msg_monitor(obj.bus.topic) as mon:
        print("---", file=obj.stdout)
        async for msg in mon:
            msg["time"] = time.time()
            msg["_time"] = datetime.datetime.now().isoformat(sep=" ", timespec="milliseconds")
            mid = msg.data.pop("_id",None)
            if mid is not None:
                msg["_id"] = mid

            m = BusMessage(**msg.data)
            msg["_data"] = m.decode()

            yprint(msg, stream=obj.stdout)
            print("---", file=obj.stdout)
            obj.stdout.flush()

def set_conn(obj, kw):
    type_ = kw.pop("type_")
    vars_ = kw.pop("vars_")
    eval_ = kw.pop("eval_")
    path_ = kw.pop("path_")
    host_ = kw.get("host")

    type_ = type_ or obj.typ
    params = process_args(obj.params, vars_, eval_, path_)
    obj.check_config(type_, host_ or obj.host, params)
    obj.typ = type_
    obj.params = params

cmd_conn = std_command(
    cmd_bus,
    "conn",
    long_name="bus connection",
    id_name=None,
    aux=(
        click.option("-t", "--type", "type_", type=str, default=None, help="Connection type"),
        click.option("-h", "--host", type=str, default=None, help="Node this may run on"),
        attr_args,
    ),
    sub_base="bus",
    sub_name=NotGiven,
    apply=set_conn,
)

@cmd_conn.command()
@click.option("-f","--force",is_flag=True,help="Force running despite wrong host")
@click.pass_obj
async def run(obj, force):
    """Stand-alone task to talk to a single server."""
    from distkv_ext.moatbus.task import gateway
    from distkv_ext.moatbus.model import conn_backend

    if not force and obj.conn.host is not None and obj.client.client_name != obj.conn.host:
        raise RuntimeError(f"Runs on {obj.conn.host} but this is {obj.client.client_name}")
    await gateway(obj.conn)

