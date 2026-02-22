"host tests"

from __future__ import annotations

import anyio
import os
import pytest
import time

from moat.util import as_service, merge, to_attrdict, yload
from moat.lib.path import P, Path
from moat.link._test import Scaffold
from moat.link.announce import announcing
from moat.link.host import HostEvent, HostState, Service, ServiceMon

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.broadcast import BroadcastReader


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
    delay: .05  # block service deletions after new run.id
    down: .15  # delayed error, give it a chance to come back
    min: .9  # answering old messages. Should be > ping timeout
  restart:
    error: .1
    flap: .2
    up: .17
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


class _FakeMon:
    def __init__(self, ping=None):
        if ping is None:
            ping = dict(stale=1.0, timeout=2.0, delete=3.0, delay=0.5)
        self.cfg = to_attrdict(dict(timeout=dict(ping=ping)))
        self.ids = {}
        self.hsi = {}
        self.actions = []
        self.last_timeout = None
        self.events = []

    def set_timeout(self, host, to=None):
        self.last_timeout = host.timeout if to is None else to

    def updated(self, host, evt):
        self.events.append((host.state, evt.transition.dest, dict(evt.kwargs)))

    async def drop_id(self, host):
        self.actions.append(("drop_id", host.id))
        host.data.pop("i", None)

    async def drop_host(self, host):
        self.actions.append(("drop_host", host.id))
        host.data.h.clear()

    async def drop_cb(self, host):
        self.actions.append(("drop_cb", host.id))
        self.ids.pop(host.id, None)


@pytest.mark.anyio
async def test_host_state_timeout_sequence():
    """The cleanup sequence removes ID entries before service entries."""
    mon = _FakeMon()
    svc = Service(mon=mon, id="svc")
    mon.ids[svc.id] = svc

    await svc.trigger(HostEvent.INIT)
    assert svc.state is HostState.NEW

    svc.data.i = {"host": "x"}
    await svc.trigger(HostEvent.MSG_ID)
    assert svc.state is HostState.ONLY_I

    svc.data.h[P("demo")] = {"id": "svc", "up": True}
    await svc.trigger(HostEvent.MSG_HOST)
    assert svc.state is HostState.ONLY_I

    svc.data.p = {"up": True, "state": "auto"}
    await svc.trigger(HostEvent.MSG_PING)
    assert svc.state is HostState.UP

    await svc.trigger(HostEvent.TIMEOUT)
    assert svc.state is HostState.TIMEOUT
    assert ("drop_id", "svc") in mon.actions
    assert "i" not in svc.data
    assert svc.data.h

    await svc.trigger(HostEvent.TIMEOUT)
    assert svc.state is HostState.STALE
    assert ("drop_host", "svc") in mon.actions
    assert not svc.data.h

    await svc.trigger(HostEvent.TIMEOUT)
    assert svc.state is HostState.DROP


@pytest.mark.anyio
async def test_host_state_recovers_before_service_delete():
    """A new ID message exits TIMEOUT before service cleanup runs."""
    mon = _FakeMon(dict(stale=0.1, timeout=0.2, delete=1.0, delay=0.3))
    svc = Service(mon=mon, id="svc")
    mon.ids[svc.id] = svc

    await svc.trigger(HostEvent.INIT)
    svc.data.i = {"host": "x"}
    await svc.trigger(HostEvent.MSG_ID)
    svc.data.h[P("demo")] = {"id": "svc", "up": True}
    await svc.trigger(HostEvent.MSG_HOST)
    svc.data.p = {"up": True, "state": "auto"}
    await svc.trigger(HostEvent.MSG_PING)
    assert svc.state is HostState.UP

    await svc.trigger(HostEvent.TIMEOUT)
    assert svc.state is HostState.TIMEOUT
    assert not svc.data.get("i")
    assert svc.data.h

    svc.data.i = {"host": "x"}
    svc.last = time.time()
    await svc.trigger(HostEvent.MSG_ID)
    assert svc.state is HostState.UP
    assert svc.data.h


@pytest.mark.anyio
async def test_host_timeout_uses_delay_without_min_key():
    """Timeout calculation uses the current config keys only."""
    mon = _FakeMon(dict(stale=0.1, timeout=0.2, delete=0.05, delay=0.3))
    svc = Service(mon=mon, id="svc")

    await svc.trigger(HostEvent.INIT)
    assert svc.timeout == pytest.approx(0.1)

    svc.data.i = {"host": "x"}
    await svc.trigger(HostEvent.MSG_ID)
    assert svc.timeout == pytest.approx(0.1)

    svc.data.h[P("demo")] = {"id": "svc", "up": True}
    await svc.trigger(HostEvent.MSG_HOST)
    assert svc.timeout == pytest.approx(0.1)

    svc.data.p = {"up": True}
    await svc.trigger(HostEvent.MSG_PING)
    assert svc.timeout == pytest.approx(0.2)

    svc.last = time.time()
    await svc.trigger(HostEvent.TIMEOUT)
    assert svc.state is HostState.TIMEOUT
    assert svc.timeout > 0.2

    await svc.trigger(HostEvent.TIMEOUT)
    assert svc.state is HostState.STALE
    assert svc.timeout == pytest.approx(0.3)


@pytest.mark.anyio
async def test_mon(cfg):
    "host monitoring test"

    # shorten timeouts
    ctim = yload(TIMES, attr=True)
    ctim.root = Path.build((os.getpid(), "TEST"))
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

            if False:
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
                await anyio.sleep(0.25)
            await anyio.sleep(0.25)
            assert len(emsgs) in (2, 3)
            assert emsgs[0]["msg"] == "not up"
            assert emsgs[-1] is Ellipsis or emsgs[-1]["msg"] == "down"
            assert 2 <= len(hmsgs) <= 4
            assert hmsgs[-2]["up"] is False
            assert hmsgs[-2]["value"] == 43
            hmsgs = []
            emsgs = []
