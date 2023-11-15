# command line interface

import datetime
import sys
from collections.abc import Mapping

import asyncclick as click
from moat.mqtt.codecs import MsgPackCodec
from moat.util import MsgReader, MsgWriter, P, Path, PathLongener, load_subgroup, yload, yprint

from moat.kv.codec import unpacker


@load_subgroup(short_help="Local data mangling", sub_pre="dump")
async def cli():
    """
    Low-level tools that don't depend on a running MoaT-KV server.
    """
    pass


@cli.command()
@click.argument("node", nargs=1)
@click.argument("file", type=click.Path(), nargs=1)
async def init(node, file):
    """Write an initial preload file.

    Usage: moat.kv dump init <node> <outfile>

    Writes an initial MoaT-KV file that behaves as if it was generated by <node>.

    Using this command, followed by "moat.kv server -l <outfile> <node>", is
    equivalent to running "moat.kv server -i 'Initial data' <node>.
    """
    async with MsgWriter(path=file) as f:
        await f(
            dict(
                chain=dict(node=node, tick=1, prev=None),
                depth=0,
                path=[],
                tock=1,
                value="Initial data",
            )
        )


@cli.command("msg")
@click.argument("path", nargs=1)
@click.pass_obj
async def msg_(obj, path):
    """
    Monitor the server-to-sever message stream.

    Use ':' for the main server's "update" stream.
    Use '+NAME' to monitor a different stream instead.
    Use '+' to monitor all streams.
    Otherwise use the given name as-is; Mosquitto wildcard rules apply.

    \b
    Common streams (prefix with '+'):
    * ping    all servers
    * update  data changes
    * del     nodes responsible for cleaning up deleted records
    """
    from moat.kv.backend import get_backend

    class _Unpack:
        def __init__(self):
            self._part_cache = dict()

    import moat.kv.server

    _Unpack._unpack_multiple = moat.kv.server.Server._unpack_multiple
    _unpacker = _Unpack()._unpack_multiple

    path = P(path)
    if len(path) == 0:
        path = P(obj.cfg.server["root"]) | "update"
    elif len(path) == 1 and path[0].startswith("+"):  # pylint: disable=no-member  # owch
        p = path[0][1:]
        path = P(obj.cfg.server["root"])
        path |= p or "#"
    be = obj.cfg.server.backend
    kw = obj.cfg.server[be]

    async with get_backend(be)(**kw) as conn:
        async with conn.monitor(*path) as stream:
            async for msg in stream:
                v = vars(msg)
                if isinstance(v.get("payload"), (bytearray, bytes)):
                    t = msg.topic
                    v = unpacker(v["payload"])
                    v = _unpacker(v)
                    if v is None:
                        continue
                    if not isinstance(v, Mapping):
                        v = {"_data": v}
                    v["_topic"] = Path.build(t)
                else:
                    v["_type"] = type(msg).__name__

                v["_timestamp"] = datetime.datetime.now().isoformat(
                    sep=" ", timespec="milliseconds"
                )

                yprint(v, stream=obj.stdout)
                print("---", file=obj.stdout)


@cli.command("post")
@click.argument("path", nargs=1)
@click.pass_obj
async def post_(obj, path):
    """
    Send a msgpack-encoded message (or several) to a specific MQTT topic.

    Messages are read from YAML.
    Common streams:
    * ping: sync: all servers (default)
    * update: data changes
    * del: sync: nodes responsible for cleaning up deleted records
    """
    from moat.kv.backend import get_backend

    path = P(path)
    be = obj.cfg.server.backend
    kw = obj.cfg.server[be]

    async with get_backend(be)(codec=MsgPackCodec, **kw) as conn:
        for d in yload(sys.stdin, multi=True):
            topic = d.pop("_topic", path)
            await conn.send(*topic, payload=d)