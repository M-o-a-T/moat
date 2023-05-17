import io
import shlex
import socket
import sys

import attr
from asyncscope import main_scope, scope
from moat.util import OptCtx, attrdict, wrap_main

from moat.kv.client import _scoped_client, client_scope

try:
    from contextlib import asynccontextmanager
except ImportError:
    from async_generator import asynccontextmanager

import logging
logger = logging.getLogger(__name__)


async def run(*args, expect_exit=0, do_stdout=True):
    args = ("-c", "/dev/null", *args)
    CFG = {}  # load_cfg("moat")

    if do_stdout:
        CFG["_stdout"] = out = io.StringIO()
    logger.debug(" moat %s", " ".join(shlex.quote(str(x)) for x in args))
    try:
        res = None
        async with OptCtx(
            main_scope(name="run") if scope.get() is None else None
        ), scope.using_scope():
            res = await wrap_main(
                args=args,
                wrap=True,
                CFG=CFG,
                cfg=False,
                name="moat",
                sub_pre="moat",
                sub_post="_main.cli",
            )
        if res is None:
            res = attrdict()
        return res
    except SystemExit as exc:
        res = exc
        assert exc.code == expect_exit, exc.code
        return exc
    except BaseException as exc:
        res = exc
        raise
    else:
        assert expect_exit == 0
        return res
    finally:
        if do_stdout:
            res.stdout = out.getvalue()
            CFG["_stdout"] = sys.stdout

