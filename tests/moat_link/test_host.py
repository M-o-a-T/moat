
"host tests"

from __future__ import annotations

import anyio
import pytest
import time
import os

from moat.link._test import Scaffold
from moat.link.meta import MsgMeta
from moat.link.host import HostState,HostMon
from moat.util import P, ensure_cfg, yload, merge, to_attrdict, as_service, Path
from moat.util.broadcast import Broadcaster

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from moat.util.broadcast import BroadcastReader


TIMES = """
timeout:
  # time after which deleted entries are flushed
  delete: 100000

  # Ping messages every … seconds
  ping: 
    every: .1
    timeout: .2  # no ping received
    delete: .4  # still no ping received
    stale: .2  # delay removal after active replacement
    down: .15  # delayed error, give it a chance to come back
    min: .9  # answering old messages. Should be > ping timeout
"""

async def run_service(sf:Scaffold, kw:dict, evt=None,*,task_status) -> Tuple[anyio.CancelScope,str]:
    """
    Task that opens a client and runs an `as_service` context.
    The task then sleeps until it's cancelled.

    Returns the cancel scope and the ID of the generated client.
    """
    kw = to_attrdict(kw)
    async with (
        sf.client_() as kw.link,
        as_service(kw) as srv,
    ):
        with anyio.CancelScope() as sc:
            task_status.started((sc,kw.link.id))
            if evt is not None:
                await evt.wait()
            srv.set()
            await anyio.sleep_forever()


async def sel_br(ibr:BroadcastReader, id:str):
    """
    Return the next broadcast message with the given ID
    """
    while True:
        hs = await anext(ibr)
        if hs.id == id:
            return hs


@pytest.mark.anyio()
async def test_mon(cfg):
    "host monitoring test"

    # shorten timeouts
    cfg = ensure_cfg("moat.link")
    ctim = yload(TIMES, attr=True)
    ctim.root = Path(os.getpid(),"TEST")
    merge(cfg.link, ctim)

    async with Scaffold(cfg, use_servers=True) as sf:
        s=await sf.server(init="TEST")

        cl = await sf.client()
        sc2,sid = await sf.tg.start(run_service,sf,dict(debug=False,dbg_host=("a","b")))

        async with HostMon(link=cl,cfg=cfg.link) as br:
            with anyio.fail_after(2):
                ibr = aiter(br)

                h = await sel_br(ibr,sid)
                assert h.state.name=="NEW",h
                for _ in range(5):
                    h = await sel_br(ibr,sid)
                    if h.state.name == "UP":
                        break
                    assert h.state.name in ("ONLY_I","ONLY_P"),h

            with anyio.move_on_after(.5):
                while True:
                    h = await sel_br(ibr,sid)
                    assert h.state.name=="UP",h

            sc2.cancel()
            with anyio.fail_after(.5):
                h = await sel_br(ibr,sid)
                if h.state.name=="STALE":
                    return # XXX investigate why that happens
                assert h.state.name=="DOWN",h
                h = await sel_br(ibr,sid)
                assert h.state.name=="DROP",h
            with anyio.move_on_after(.5):
                h = await sel_br(ibr,sid)
                assert False, h
