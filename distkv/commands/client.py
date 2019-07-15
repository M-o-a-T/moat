# command line interface

import os
import sys
import trio_click as click
import json
from functools import partial

from distkv.util import (
    attrdict,
    combine_dict,
    PathLongener,
    MsgReader,
    PathShortener,
    split_one,
    NotGiven,
)
from distkv.client import open_client, StreamedRequest
from distkv.command import Loader
from distkv.default import CFG
from distkv.server import Server
from distkv.auth import loader, gen_auth
from distkv.exceptions import ClientError

import logging

logger = logging.getLogger(__name__)


class NullObj:
    """
    This helper defers raising an exception until one of its attributes is
    actually accessed.
    """

    def __init__(self, exc):
        self._exc = exc

    def __call__(self, *a, **kw):
        raise self._exc

    def __await__(self):
        raise self._exc

    def __getattr__(self, k):
        if k[0] == "_" and k != "_request":
            return object.__getattribute__(self, k)
        raise self._exc


@main.group(cls=partial(Loader, __file__, "client"))
@click.option(
    "-h", "--host", default=None, help="Host to use. Default: %s" % (CFG.connect.host,)
)
@click.option(
    "-p",
    "--port",
    type=int,
    default=None,
    help="Port to use. Default: %d" % (CFG.connect.port,),
)
@click.option(
    "-a",
    "--auth",
    type=str,
    default=None,
    help="Auth params. =file or 'type param=value…' Default: _anon",
)
@click.option("-m", "--metadata", is_flag=True, help="Include/print metadata.")
@click.pass_context
async def cli(ctx, host, port, auth, metadata):
    """Talk to a DistKV server."""
    obj = ctx.obj
    cfg = attrdict()
    if host is not None:
        cfg.host = host
    if port is not None:
        cfg.port = port

    if auth is not None:
        cfg.auth = gen_auth(auth)
        if obj._DEBUG:
            cfg.auth._DEBUG = True

    cfg = combine_dict(cfg, CFG.connect, cls=attrdict)

    obj.meta = metadata

    try:
        obj.client = await ctx.enter_async_context(open_client(**cfg))
    except OSError as exc:
        obj.client = NullObj(exc)
    else:
        logger.debug("Connected.")
