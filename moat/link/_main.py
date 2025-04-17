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

from moat.util import NotGiven, P, Path, load_subgroup, yprint
from moat.util.times import ts2iso

from .backend import RawMessage, get_backend
from .client import Link

logger = logging.getLogger(__name__)

usage1 = """
"moat link" requires configuration. It should look like this:

    link:
        backend:
            driver: mqtt
            host: localhost
            port: 1883
            user: foo
            pass: bar
        root: !P moat.something-unique
        codec: std-cbor

The MQTT hierarchy below the "root" topic, with slashes instead of dots,
*must* be empty when you start a new installation.

Please add this stanza to the file "/etc/moat/moat.cfg" (or "/etc/moat.cfg",
or "~/.local/moat.cfg") and try again.
"""

usage2 = """
"moat link" requires a root topic.

This entry should be tagged with '!P' and be some dot-separated names.
For clarity it should start with 'moat.', though that's just a
recommendation.

Your MQTT server cannot contain any retained topics under that name
(when replacing the dots with slashes) when you start a new installation.

Config example:

    link:
        backend:
            …
        prefix: !P moat.com.your-domain

"""

usage9 = """

"moat link" requires at least one history server for stable operation.

Please run "sudo systemctl start moat-link-server", or
start "moat link server" in a separate terminal, and try again.
"""



@load_subgroup(sub_pre="moat.link", sub_post="cli", ext_pre="moat.link", ext_post="_main.cli")
@click.option("-n","--name", type=str, help="Name of this client (or server)")
@click.pass_context
async def cli(ctx,name):
    """
    MoaT's data link

    This collection of commands is useful for managing and building MoaT itself.
    """
    obj = ctx.obj
    cfg = obj.cfg
    obj.name = name

    if "link" not in cfg or "backend" not in cfg["link"]:
        sys.stderr.write(usage1)
        raise click.UsageError("not configured")
    cfg = cfg["link"]
    if not isinstance(cfg.root, Path) or cfg.root == Path("XXX"):
        sys.stderr.write(usage2)
        raise click.UsageError("badly configured")


@cli.command("test")
@click.pass_obj
async def test(obj):
    "Test"

    cfg = obj.cfg.link
    async def check_root(evt, *, task_status):
        with anyio.CancelScope() as sc:
            task_status.started(sc)
            async with back.monitor(cfg.root) as mon:
                async for msg in mon:
                    print("Root dataset:")
                    yprint(msg.data)
                    evt.set()
                    return

    async with get_backend(cfg) as back,back.connect(), anyio.create_task_group() as tg:
        evt = anyio.Event()
        t = anyio.current_time()
        cs = await tg.start(check_root, evt)

        
        try:
            with anyio.fail_after(max(1+t-anyio.current_time(),.1)):
                await evt.wait()
        except TimeoutError:
            cs.cancel()
            print(f"No root dataset on {cfg.root} found.")
        


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


async def do_pub(client, args, cfg):
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
                tg.start_soon(partial(client.send, topic, message, qos=qos, retain=retain))
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
@click.pass_obj
async def pub(obj, **args):
    """Publish one or more MoaT-Link messages"""
    if args["msg_stdin"] + args["msg_stdin_lines"] + args["msg_stdin_eval"] > 1:
        raise click.UsageError("You can only read from stdin once")
    cfg = obj.cfg.link
    name = args["name"] or cfg.get("name", None)

    if args["keep_alive"]:
        cfg["keep_alive"] = args["keep_alive"]

    if not obj.name:
        raise UsageError("You must supply a client name")

    async with get_backend(cfg, name=obj.name) as back, anyio.create_task_group() as tg:
        await do_pub(back, args, cfg)


async def do_sub(client, args, cfg):
    "handle subscriptions"
    lock = anyio.Lock()
    try:
        async with anyio.create_task_group() as tg:
            for topic in args["topic"]:
                tg.start_soon(run_sub, client, topic, args, cfg, lock)

    except KeyboardInterrupt:
        pass
    except MQTTException as ce:
        logger.fatal("connection to '%s' failed: %r", args["uri"], ce)


async def run_sub(client, topic, args, cfg, lock):
    "handle a single subscription"
    qos = args["qos"] or cfg["qos"]
    max_count = args["n_msg"]
    count = 0

    async with client.monitor(topic, qos=qos) as subscr:
        async for msg in subscr:
            async with lock:
                if args["yaml"]:
                    d = dict(topic = msg.topic, time= (tm := time.time()))
                    d["_time"] = ts2iso(tm, delta=True, msec=6)
                    if isinstance(msg, RawMessage):
                        d["raw"] = msg.data
                        d["error"] = repr(msg.exc)
                    else:
                        d["data"] = msg.data
                    d["meta"] = msg.meta.repr()
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
@click.option("-n", "--n_msg", type=int, default=0, help="Number of messages to read (per topic)")
@click.option("-k", "--keep-alive", type=float, help="Keep-alive timeout (seconds)")
@click.pass_obj
async def sub(obj, **args):
    """Read or monitor one or more MoaT-Link topics"""
    cfg = obj.cfg.link

    name = args["name"] or cfg.get("id", None)

    if args["keep_alive"]:
        cfg["keep_alive"] = args["keep_alive"]

    async with get_backend(cfg, name=obj.name) as back, anyio.create_task_group() as tg:
        await do_sub(back, args, cfg)
