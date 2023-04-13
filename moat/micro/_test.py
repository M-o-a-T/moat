"""
Test runner
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from moat.util import attrdict, merge, packer, yload

from moat.micro.compat import TaskGroup
from moat.micro.main import Request, get_link, get_link_serial
from moat.micro.proto.multiplex import Multiplexer

import logging
logging.basicConfig(level=logging.DEBUG)

@asynccontextmanager
async def mpy_server(
    temp: Path, debug=True, lossy=False, guarded=False, req=Request, cff="test", cfg={}
):
    obj = attrdict()
    obj.debug = debug
    obj.lossy = lossy
    obj.guarded = guarded
    obj.socket = temp / "moat.sock"

    cff = Path(__file__).parent / f"{cff}.cfg"
    with open(cff, "r") as f:
        cf = yload(f)
    cfg = merge(cf, cfg)
    cfg["link"]["guarded"] = guarded
    cfg["link"]["lossy"] = lossy

    @asynccontextmanager
    async def _factory(req):
        try:
            os.stat("micro/lib")
        except OSError:
            pre = ""
        else:
            pre = "micro/"

        root = temp / "root"
        try:
            root.mkdir()
        except EnvironmentError:
            pass
        with (root / "moat.cfg").open("wb") as f:
            f.write(packer(cfg))

        argv = [
            # "strace","-s300","-o/tmp/bla",
            pre + "lib/micropython/ports/unix/build-standard/micropython",
            pre + "tests-mpy/mplex.py",
            str(root),
        ]

        async with await anyio.open_process(argv, stderr=sys.stderr) as proc:
            ser = anyio.streams.stapled.StapledByteStream(proc.stdin, proc.stdout)
            async with get_link_serial(obj, ser, request_factory=req,
                    use_console=not lossy) as link:
                yield link

    mplex = Multiplexer(_factory, obj.socket, cfg=cfg, load_cfg=True)
    async with TaskGroup() as tg:
        srv = await tg.spawn(mplex.serve, _name="serve")
        with anyio.fail_after(3):
            await mplex.wait()
        obj.server = mplex
        obj.cfg = cfg
        yield obj
        srv.cancel()


@asynccontextmanager
async def mpy_client(obj, **kw):
    kw.setdefault("request_factory", Request)

    async with get_link(obj, cfg=obj.cfg, **kw) as link:
        yield link
