"""
This module describes the MoaT data link.
"""

from __future__ import annotations

import anyio

# pylint: disable=missing-module-docstring
import logging
import sys
from functools import partial
from pathlib import Path as FSPath
import time

import asyncclick as click

from mqttproto import MQTTException

from moat.util import NotGiven, P, Path, load_subgroup, yprint, gen_ident, PathLongener
from moat.util.path import set_root
from moat.util.times import ts2iso,humandelta
from moat.lib.codec import get_codec

from moat.link.backend import RawMessage, get_backend

try:
    from mqttproto import MQTTPublishPacket
except ImportError:
    MQTTPublishPacket = NotGiven


logger = logging.getLogger(__name__)

@click.group
@click.pass_context
async def cli(ctx):
    """
    Commands that bypass the MoaT-Link server

    These access the MQTT backend directly.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    if not obj.name:
        obj.name = "mon_"+gen_ident()

    set_root(cfg)
    obj.conn = await ctx.with_async_resource(get_backend(cfg, name=obj.name))


@cli.command()
@click.argument("file", type=click.Path(), nargs=1)
async def init(file):
    """Write an initial preload file.

    Usage: moat link raw init <node> <outfile>

    Writes an initial MoaT-Link data file.

    Using this command, followed by "moat kv server -l <outfile> <node>", is
    equivalent to running "moat kv server -i 'Initial data' <node>.
    """
    from moat.link.meta import MsgMeta
    from moat.util.msg import MsgWriter
    from moat.util.cbor import gen_start,gen_stop

    meta=MsgMeta(origin="init")
    async with MsgWriter(path=file, codec="std-cbor") as f:
        await f(gen_start("Initial link data file",mode="init"))
        await f([0,P(":"),dict(type="MoaT-Link data"),*meta.dump()])
        await f(gen_stop(mode="log_end"))

@cli.command("test")
@click.pass_obj
async def test(obj):
    "Test"

    lock = anyio.Lock()
    cfg = obj.cfg.link
    async def check_root():
        try:
            with anyio.fail_after(1) as sc:
                async with back.monitor(cfg.root) as mon:
                    async for msg in mon:
                        async with lock:
                            print("Root dataset:")
                            yprint(msg.data)
                            print("---")
                            return
        except TimeoutError:
            print(f"No retained root dataset on {cfg.root} found.")

    async def check_server():
        try:
            with anyio.fail_after(1) as sc:
                async with back.monitor(cfg.root+P("run.service.main")) as mon:
                    async for msg in mon:
                        async with lock:
                            print("Server broadcast:")
                            yprint(msg.data)
                            print("---")
                            return
        except TimeoutError:
            print(f"No retained root dataset on {cfg.root} found.")


    async with get_backend(cfg) as back,back.connect(), anyio.create_task_group() as tg:
        tg.start_soon(check_root)
        tg.start_soon(check_server)
        


def _get_message(args):
    for m in args["msg"]:
        yield m
    for m in args["msg_eval"]:
        yield eval(m)  # pylint: disable=eval-used
    if args["msg_lines"]:
        with open(args["msg_lines"]) as f:  # pylint: disable=unspecified-encoding
            for line in f:
                yield line.encode(encoding="utf-8")
    if args["msg_stdin_lines"]:
        for line in sys.stdin:
            if line:
                yield line.encode(encoding="utf-8")
    if args["msg_stdin"]:
        yield sys.stdin.buffer.read()
    if args["msg_stdin_eval"]:
        message = sys.stdin.read()
        yield eval(message)  # pylint: disable=eval-used


async def do_pub(client, args, cfg, codec):
    logger.info("%s Connected to broker", client.name)
    for k, v in args.items():
        if v is None or v is NotGiven:
            continue
        cfg[k] = v

    try:
        topic = args["topic"]
        retain = args["retain"]
        qos = args["qos"] or cfg["qos"]

        async with anyio.create_task_group() as tg:
            for message in _get_message(args):
                logger.info("%s Publishing to '%s'", client.name, topic)
                tg.start_soon(partial(client.send, topic, message, qos=qos, retain=retain, codec=codec))
        logger.info("%s Disconnected from broker", client.name)
    except KeyboardInterrupt:
        logger.info("%s Disconnected from broker", client.name)


@cli.command()
@click.option("-i", "--client_id", "--name", "name", help="string to use as client ID")
@click.option("-q", "--qos", type=click.IntRange(0, 2), help="Quality of service to use (0-2)")
@click.option("-r", "--retain", is_flag=True, help="Set the Retain flag")
@click.option("-t", "--topic", type=P, required=True, help="Message path")
@click.option("-m", "--msg", multiple=True, help="Message data (may be repeated)")
@click.option(
    "-M",
    "--msg-eval",
    multiple=True,
    help="Message data (Python, evaluated, may be repeated)",
)
@click.option(
    "-f",
    "--msg-lines",
    type=click.File("r"),
    help="File with messages (each line sent separately",
)
@click.option("-R", "--msg-stdin", is_flag=True, help="Single message from stdin")
@click.option(
    "-s",
    "--msg-stdin-lines",
    is_flag=True,
    help="Messages from stdin (each line sent separately",
)
@click.option(
    "-S",
    "--msg-stdin-eval",
    is_flag=True,
    help="Python code that evaluates to the message on stdin",
)
@click.option("-k", "--keep-alive", type=float, help="Keep-alive timeout (seconds)")
@click.option("-c", "--codec", type=str, default="noop", help="codec to use (default: noop)")
@click.pass_obj
async def pub(obj, **args):
    """Publish one or more MoaT-Link messages.

    This command directly accesses the MQTT server: it works without a
    working MoaT-Link server.
    """
    if args["msg_stdin"] + args["msg_stdin_lines"] + args["msg_stdin_eval"] > 1:
        raise click.UsageError("You can only read from stdin once")
    cfg = obj.cfg.link
    name = args["name"] or cfg.get("name", None)
    codec = get_codec(args["codec"])

    if args["keep_alive"]:
        cfg["keep_alive"] = args["keep_alive"]

    if not obj.name:
        raise UsageError("You must supply a client name")

    async with anyio.create_task_group() as tg:
        await do_pub(obj.conn, args, cfg, codec)

async def run_kvsub(client, topic, lock):
    """Monitor a MoaT-KV subtree"""

    if topic[-1] == "#":
        topic = topic.parent
        depth=-1
    else:
        depth=0
    async with client.watch(
        topic,
        nchain=2,
        fetch=True,
        max_depth=depth,
        long_path=False,
    ) as res:
        pl = PathLongener(topic)
        async for r in res:
            async with lock:
                tm = time.time()
                atm = anyio.current_time()

                #if "value" in r:
                #    add_dates(r.value)
                pl(r)
                if r.get("state", "") == "uptodate":
                    continue
                del r["seq"]

                r["_prev"] = humandelta(atm-lock.tm,msec=6)
                r["_time"] = ts2iso(tm, msec=6)
                r["time"] = tm

                yprint(r)
                print("---")
                lock.tm=atm

async def do_sub(client, args, cfg):
    "handle subscriptions"
    lock = anyio.Lock()
    lock.tm = anyio.current_time()
    try:
        async with anyio.create_task_group() as tg:
            for topic in args["topic"]:
                tg.start_soon(run_sub, client, topic, args, cfg.link, lock)
            if args["kv_topic"]:
                from moat.kv.client import open_client as kv_client
                async with kv_client(**cfg.kv) as kvc:
                    for topic in args["kv_topic"]:
                        tg.start_soon(run_kvsub, kvc, topic, lock)



    except KeyboardInterrupt:
        pass
    except MQTTException as ce:
        logger.fatal("connection to '%s' failed: %r", args["uri"], ce)


async def run_sub(client, topic, args, cfg, lock):
    "handle a single subscription"
    qos = args["qos"] or cfg["qos"]
    max_count = args["n_msg"]
    count = 0
    dcbor=get_codec("std-cbor")
    dmsgpack=get_codec("std-msgpack")

    async with client.monitor(topic, qos=qos, codec=args.get("codec","noop")) as subscr:
        async for msg in subscr:
            async with lock:
                if args["yaml"]:
                    tm = time.time()
                    atm = anyio.current_time()

                    d = dict(topic = msg.topic, time=tm, _prev = humandelta(atm-lock.tm,msec=6),_time = ts2iso(tm, msec=6))

                    if isinstance(msg, RawMessage):
                        d["raw"] = msg.data
                        d["error"] = repr(msg.exc)
                    else:
                        d["data"] = msg.data
                    if msg.meta is not None:
                        d["meta"] = msg.meta.repr()

                    try:
                        d["data_cbor"] = dcbor.decode(msg.data)
                    except Exception:
                        pass

                    try:
                        d["data_msgpack"] = dmsgpack.decode(msg.data)
                    except Exception:
                        pass

                    flags = ""
                    if msg.retain:
                        flags += "R"
                    #if msg.qos > 0:
                    #    flags += f"Q{int(msg.qos)}"
                    if flags:
                        d["_flags"] = flags

                    lock.tm=atm
                    yprint(d)
                    print("---")
                else:
                    if isinstance(msg, RawMessage):
                        print(msg.topic, "*", msg.data, repr(msg.exc), sep="\t")
                    else:
                        print(msg.topic, msg.data, sep="\t")
            count += 1
            if max_count and count >= max_count:
                break


@cli.command()
@click.option("-i", "--client_id", "--name", "name", help="string to use as client ID")
@click.option("-q", "--qos", type=click.IntRange(0, 2), help="Quality of service to use (0-2)")
@click.option("-y", "--yaml", is_flag=True, help="Print output as YAML stream")
@click.option(
    "-t",
    "--topic",
    multiple=True,
    type=P,
    help="Message topic, dot-separated (can be used more than once)",
)
@click.option(
    "-T",
    "--kv-topic",
    multiple=True,
    type=P,
    help="Message topic from MoaT-KV legacy, dot-separated (can be used more than once)",
)
@click.option("-n", "--n_msg", type=int, default=0, help="Number of messages to read (per topic)")
@click.option("-k", "--keep-alive", type=float, help="Keep-alive timeout (seconds)")
@click.pass_obj
async def sub(obj, **args):
    """
    Monitor one or more MoaT-Link topics.

    This command directly accesses the MQTT server: it works without a
    working MoaT-Link server.
    """
    cfg = obj.cfg

    name = args["name"] or cfg.link.get("id", None)

    if args["keep_alive"]:
        cfg.link["keep_alive"] = args["keep_alive"]

    await do_sub(obj.conn, args, cfg)
