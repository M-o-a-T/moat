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

import asyncclick as click
from mqttproto import MQTTException

from moat.util import NotGiven, P, Path, load_subgroup

from .backend import RawMessage
from .client import open_link

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
        codec: cbor

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

The MQTT hierarchy below the root topic, with slashes instead of dots,
*must* be empty when you start a new installation.

Config example:

    link:
        backend:
            …
        prefix: !P moat.your-domain.prod

"""

usage9 = """

"moat link" requires at least one history server for stable operation.

Please run "sudo systemctl start moat-link-server", or
start "moat link server" in a separate terminal, and try again.
"""


@load_subgroup(sub_pre="moat.link", sub_post="cli", ext_pre="moat.link", ext_post="_main.cli")
@click.pass_context
async def cli(ctx):
    """
    MoaT's data link

    This collection of commands is useful for managing and building MoaT itself.
    """
    cfg = ctx.obj.cfg
    if "link" not in cfg or "backend" not in cfg["link"]:
        sys.stderr.write(usage1)
        raise click.UsageError("not configured")
    cfg = cfg["link"]
    if not isinstance(cfg.get("root"), Path):
        sys.stderr.write(usage2)
        raise click.UsageError("badly configured")


@cli.command("test")
def test():
    "Test"
    print(FSPath(__file__).parent / "_templates")


def _get_message(args):
    for m in args["msg"]:
        yield m
    for m in args["msg_eval"]:
        yield eval(m)  # pylint: disable=eval-used  # noqa:S307
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
        yield eval(message)  # pylint: disable=eval-used  # noqa:S307


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
@click.option("-r", "--retain", "retain", flag_value=True, help="Set the Retain flag")
@click.option("--no-retain", "retain", flag_value=False, help="Clear the Retain flag")
@click.option(
    "--default-retain",
    "retain",
    flag_value=None,
    help="Use the Retain flag's default",
    hidden=True,
)
@click.option("-t", "--topic", type=P, required=True, help="Message topic, '/'-separated")
@click.option("-m", "--msg", multiple=True, help="Message data (may be repeated)")
@click.option(
    "-M", "--msg-eval", multiple=True, help="Message data (Python, evaluated, may be repeated)"
)
@click.option(
    "-f", "--msg-lines", type=click.File("r"), help="File with messages (each line sent separately"
)
@click.option("-R", "--msg-stdin", is_flag=True, help="Single message from stdin")
@click.option(
    "-s", "--msg-stdin-lines", is_flag=True, help="Messages from stdin (each line sent separately"
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
    """Publish one or more MQTT messages"""
    if args["msg_stdin"] + args["msg_stdin_lines"] + args["msg_stdin_eval"] > 1:
        raise click.UsageError("You can only read from stdin once")
    cfg = obj.cfg.link
    name = args["name"] or cfg.get("name", None)

    if args["keep_alive"]:
        cfg["keep_alive"] = args["keep_alive"]

    async with open_link(cfg, name=name) as C:
        await do_pub(C, args, cfg)


async def do_sub(client, args, cfg):
    "handle subscriptions"
    try:
        async with anyio.create_task_group() as tg:
            for topic in args["topic"]:
                tg.start_soon(run_sub, client, topic, args, cfg)

    except KeyboardInterrupt:
        pass
    except MQTTException as ce:
        logger.fatal("connection to '%s' failed: %r", args["uri"], ce)


async def run_sub(client, topic, args, cfg):
    "handle a single subscription"
    qos = args["qos"] or cfg["qos"]
    max_count = args["n_msg"]
    count = 0

    async with client.monitor(topic, qos=qos) as subscr:
        async for message in subscr:
            if isinstance(message, RawMessage):
                print(message.topic, "*", message.data, repr(message.exc), sep="\t")
            else:
                print(message.topic, message.data, sep="\t")
            count += 1
            if max_count and count >= max_count:
                break


@cli.command()
@click.option("-i", "--client_id", "--name", "name", help="string to use as client ID")
@click.option("-q", "--qos", type=click.IntRange(0, 2), help="Quality of service to use (0-2)")
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
    """Subscribe to one or more MQTT topics"""
    cfg = obj.cfg.link

    name = args["name"] or cfg.get("id", None)

    if args["keep_alive"]:
        cfg["keep_alive"] = args["keep_alive"]

    async with open_link(cfg, name=name) as C:
        await do_sub(C, args, cfg)
