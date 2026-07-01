# command line interface  # noqa: D100
from __future__ import annotations

import sys

import asyncclick as click

from moat.util import yload, yprint
from moat.lib.path import P
from moat.lib.run import AliasedGroup
from moat.link.client import Link
from moat.link.meta import MsgMeta


@click.group(cls=AliasedGroup, short_help="Manage codecs.")
@click.option("-m", "--meta", is_flag=True, help="include metadata")
@click.pass_context
async def cli(ctx, meta):
    """
    Manage MoaT-Link codecs and converters.

    Codecs store Python snippets to encode/decode some data.
    A codec must include test vectors.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(
        Link(cfg, common=True, only=getattr(obj, "link_name", None))
    )
    obj.meta = meta
    obj.codec_prefix = obj.cfg.link.codec.prefix


@cli.command()
@click.option("-e", "--encode", type=click.File(mode="w", lazy=True), help="Save the encoder here")
@click.option("-d", "--decode", type=click.File(mode="w", lazy=True), help="Save the decoder here")
@click.option("-s", "--script", type=click.File(mode="w", lazy=True), help="Save the data here")
@click.argument("path", type=P, nargs=1)
@click.pass_obj
async def get(obj, path, script, encode, decode):
    """Read a codec entry."""
    if not len(path):
        raise click.UsageError("You need a non-empty path.")

    full = obj.codec_prefix + path
    try:
        val, *m = await obj.conn.d.get(full)
    except KeyError as exc:
        raise click.UsageError(f"No codec entry at {full!s}") from exc
    meta = MsgMeta.restore(m)

    if not isinstance(val, dict):
        raise click.UsageError(f"Codec entry at {full!s} is not a mapping.")

    val = dict(val)
    if encode and val.get("encode") is not None:
        encode.write(val.pop("encode"))
    if decode and val.get("decode") is not None:
        decode.write(val.pop("decode"))

    if obj.meta:
        out = {"value": val, "meta": meta.dump()}
    else:
        out = val
    yprint(out, stream=script or obj.stdout)


@cli.command(name="list")
@click.argument("path", type=P, nargs=1, default=P(":"))
@click.pass_obj
async def list_(obj, path):
    """List codec entries below ``PATH``."""
    full = obj.codec_prefix + path
    seen = False
    async with obj.conn.d_walk(full) as mon:
        async for p, _d in mon:
            seen = True
            print(path + p, file=obj.stdout)
    if not seen and obj.debug:
        print("- no codec entries.", file=sys.stderr)


@cli.command("set")
@click.option("-e", "--encode", type=click.File(mode="r"), help="File with the encoder")
@click.option("-d", "--decode", type=click.File(mode="r"), help="File with the decoder")
@click.option("-D", "--data", type=click.File(mode="r"), help="File with the rest")
@click.option("-i", "--in", "in_", nargs=2, multiple=True, help="Decoding sample")
@click.option("-o", "--out", nargs=2, multiple=True, help="Encoding sample")
@click.argument("path", type=P, nargs=1)
@click.pass_obj
async def set_(obj, path, encode, decode, data, in_, out):
    """Save codec information at ``PATH`` (below the codec prefix)."""
    if not len(path):
        raise click.UsageError("You need a non-empty path.")

    msg = yload(data) if data else {}
    if "value" in msg:
        msg = msg["value"]

    if "encode" in msg:
        if encode:
            raise click.UsageError("Duplicate encode script")
    else:
        if not encode:
            raise click.UsageError("Missing encode script")
        msg["encode"] = encode.read()
    if "decode" in msg:
        if decode:
            raise click.UsageError("Duplicate decode script")
    else:
        if not decode:
            raise click.UsageError("Missing decode script")
        msg["decode"] = decode.read()
    if in_:
        msg["in"] = [(eval(a), eval(b)) for a, b in in_]
    if out:
        msg["out"] = [(eval(a), eval(b)) for a, b in out]

    if not msg.get("in"):
        raise click.UsageError("Missing decode tests")
    if not msg.get("out"):
        raise click.UsageError("Missing encode tests")

    full = obj.codec_prefix + path
    res = await obj.conn.d_set(full, msg, meta=obj.meta)
    if obj.meta:
        yprint(res, stream=obj.stdout)
