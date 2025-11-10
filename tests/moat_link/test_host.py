"host tests"

from __future__ import annotations

import anyio
import os
import pytest

from moat.util import P, Path, as_service, ensure_cfg, merge, to_attrdict, yload
from moat.link._test import Scaffold
from moat.link.announce import announcing
from moat.link.host import ServiceMon

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
  restart:
    error: .1
    flap: .3
    up: .2
"""


async def run_service(
    sf: Scaffold, kw: dict, evt=None, *, task_status
) -> tuple[anyio.CancelScope, str]:
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
            task_status.started((sc, kw.link.id))
            if evt is not None:
                await evt.wait()
            srv.set()
            await anyio.sleep_forever()


async def sel_br(ibr: BroadcastReader, id: str):
    """
    Return the next broadcast message with the given ID
    """
    while True:
        hs = await anext(ibr)
        if hs.id == id:
            return hs


@pytest.mark.anyio
async def test_mon(cfg):
    "host monitoring test"

    # shorten timeouts
    cfg = ensure_cfg("moat.link")
    ctim = yload(TIMES, attr=True)
    ctim.root = Path(os.getpid(), "TEST")
    merge(cfg.link, ctim)
    emsgs = []
    hmsgs = []

    async def mon_err(cl):
        async with cl.d_watch(P("error.run.host"), subtree=True) as mon:
            async for p, m in mon:
                assert p == P("test123.test.mon")
                emsgs.append(m)

    async def mon_host(cl):
        async with cl.d_watch(P("run.host.test123.test"), subtree=True) as mon:
            async for p, m in mon:
                assert p == P("mon")
                hmsgs.append(m)

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")

        cl = await sf.client()
        sc2, sid = await sf.tg.start(run_service, sf, dict(debug=False, dbg_host=("a", "b")))
        sf.tg.start_soon(mon_err, cl)
        sf.tg.start_soon(mon_host, cl)

        async with ServiceMon(link=cl, cfg=cfg.link) as br:
            with anyio.fail_after(2):
                ibr = aiter(br)

                h = await sel_br(ibr, sid)
                assert h.state.name == "NEW", h
                for _ in range(5):
                    h = await sel_br(ibr, sid)
                    if h.state.name == "UP":
                        break
                    assert h.state.name in ("ONLY_I", "ONLY_P"), h

            with anyio.move_on_after(0.5):
                while True:
                    h = await sel_br(ibr, sid)
                    assert h.state.name == "UP", h

            sc2.cancel()
            with anyio.fail_after(0.5):
                h = await sel_br(ibr, sid)
                if h.state.name == "STALE":
                    return  # XXX investigate why that happens
                while h.state.name == "DOWN":
                    h = await sel_br(ibr, sid)
                assert h.state.name == "DROP", h
            with anyio.move_on_after(0.5):
                h = await sel_br(ibr, sid)
                raise AssertionError(h)

            if True:
                async with cl.announcing(host="test123", name=P("test.mon")) as s:
                    await anyio.sleep(0.5)
                await anyio.sleep(0.5)
                assert len(emsgs) == 3
                assert emsgs[0]["msg"] == "not up"
                assert emsgs[1] is Ellipsis
                assert emsgs[2]["msg"] == "down"
                assert len(hmsgs) == 2
                assert hmsgs[0]["up"] is False
                assert hmsgs[1] is Ellipsis
                hmsgs = []
                emsgs = []
                # should update state when setting
                # should error when not started after TIME

                async with announcing(cl, host="test123", name=P("test.mon")) as s:
                    s.set()
                    await anyio.sleep(0.5)
                    assert len(emsgs) == 1
                await anyio.sleep(0.5)
                assert len(emsgs) == 2
                assert emsgs[0] is Ellipsis
                assert emsgs[1]["msg"] == "down"
                assert len(hmsgs) == 3
                assert hmsgs[0]["up"] is False
                assert hmsgs[1]["up"] is True
                assert hmsgs[2] is Ellipsis
                hmsgs = []
                emsgs = []

                async with cl.announcing(host="test123", name=P("test.mon")) as s:
                    await anyio.sleep(0.1)
                    s.set()
                    await anyio.sleep(0.1)
                    s.value = 42
                    await anyio.sleep(0.1)
                assert len(emsgs) == 0
                await anyio.sleep(0.1)
                assert len(emsgs) == 1
                assert emsgs[0]["msg"] == "flapping"

                assert 2 <= len(hmsgs) <= 4
                assert hmsgs[0]["up"] is False
                assert hmsgs[1]["up"] is True
                assert hmsgs[-2]["up"] is True
                assert hmsgs[-2]["value"] == 42
                assert hmsgs[-1] is Ellipsis
                hmsgs = []
                emsgs = []

            async with cl.announcing(host="test123", name=P("test.mon")) as s:
                s.value = 43
                await anyio.sleep(0.35)
            assert len(emsgs) == 2
            assert emsgs[0]["msg"] == "not up"
            assert emsgs[1] is Ellipsis
            assert 2 <= len(hmsgs) <= 4
            assert hmsgs[-2]["up"] is False
            assert hmsgs[-2]["value"] == 43
            hmsgs = []
            emsgs = []

            await anyio.sleep(0.5)
