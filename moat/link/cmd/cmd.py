# command line interface  # noqa: D100
from __future__ import annotations

import asyncclick as click

from moat.util import NotGiven, P, attr_args, process_args, yprint
from moat.link.client import Link


@click.command(short_help="Send a command")
@click.option("-S", "--stream", is_flag=True, help="Read a stream")
@click.option("-R", "--raw", is_flag=True, help="Show raw message data")
@click.argument("path", type=P, nargs=1)
@click.pass_context
@attr_args
async def cli(ctx, path, stream, raw, **kw):
    """
    Send a command to the server.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    if obj.get("port", None) is not None:
        cfg.client.port = obj.port

    async with Link(cfg) as conn:
        val = process_args(NotGiven, **kw)
        kw = {}
        if isinstance(val, list):
            args = val
        elif isinstance(val, dict):
            args = []
            for k, v in list(val.items()):
                if k.startswith("_"):
                    try:
                        k = int(k[1:])  # noqa:PLW2901
                    except ValueError:
                        pass
                    else:
                        if k >= len(args):
                            args += [NotGiven] * (k - len(args) + 1)
                        args[k] = v
                        continue
                kw[k] = v
        elif val is NotGiven:
            args = []
        else:
            args = [val]

        if stream:
            async with conn.cmd(path, *args, **kw).stream_in() as res:
                yprint(rep_(res, raw), stream=obj.stdout)
                print("---", file=obj.stdout)
                async for msg in res:
                    yprint(rep_(msg, raw), stream=obj.stdout)
                    print("---", file=obj.stdout)
        else:
            res = await conn.cmd(path, *args, **kw)
        yprint(rep_(res, raw), stream=obj.stdout)


def rep_(res, raw=False):  # noqa: D103
    if raw:
        return res.args + [res.kw]
    if not res.args:
        return res.kw
    if res.kw:
        return res.args + [res.kw]
    if len(res.args) == 1:
        return res.args[0]
    return res.args
