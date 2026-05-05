from __future__ import annotations  # noqa: D100

import anyio
import copy
import pytest
import time
from contextlib import AsyncExitStack
from functools import partial
from unittest import mock

import trio

from moat.util import combine_dict, to_attrdict
from moat.kv.client import open_client as KVClient
from moat.kv.data import data_get as kvdata_get
from moat.kv.server import Server as KVServer
from moat.lib.codec import get_codec
from moat.lib.path import P
from moat.link._data import backend_get, data_get
from moat.link._test import Scaffold
from moat.link.client import Link
from moat.link.gate import DelayedGate, GateNode, run_gate
from moat.link.gate.link import Gate as LinkGate
from moat.link.meta import MsgMeta

from typing import cast


async def mon(c, *, task_status):  # noqa: D103
    async with c.monitor(P(":"), subtree=True, raw=True) as mo:
        task_status.started()
        c1 = get_codec("std-cbor")
        c2 = get_codec("std-msgpack")
        async for msg in mo:
            try:
                data = c1.decode(msg.data)
                meta = MsgMeta.decode(msg.meta)
            except Exception:
                pass
            else:
                print("***** cbor", msg.topic, data, meta)
                continue

            try:
                data = c2.decode(msg.data)
            except Exception:
                pass
            else:
                print("***** msgp", msg.topic, data, msg.meta)
                continue

            print("***** raw ", msg.topic, msg.data, msg.meta)


@pytest.mark.anyio
async def test_gate_mqtt(cfg):  # noqa: D103
    async with Scaffold(cfg, use_servers=True) as sf:
        # await sf.tg.start(_dump, sf)
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()
        cc = await sf.client()
        cm = await sf.client()
        await sf.tg.start(mon, cm)

        codec = get_codec("json")

        await c.d_set(P("test.a.one"), 1)
        await c.d_set(P("test.a.two"), 2)
        await c.send(P("test.b.two"), 22, codec=codec, retain=True)
        await c.send(P("test.b.three"), 33, codec=codec, retain=True)

        async def mon_src(task_status):
            async with c.d_watch(P("test.a")) as mon:
                got = []
                task_status.started(got)
                async for p, d in mon:
                    got.append((p, d))

        async def mon_dst(task_status):
            async with c.monitor(P("test.b"), codec=codec) as mon:
                got = []
                task_status.started(got)
                async for m in mon:
                    got.append((m.path, m.data))

        await sf.tg.start(mon_src)
        await sf.tg.start(mon_dst)

        await c.d_set(
            P("gate.test"),
            dict(
                driver="mqtt",
                src=P("test.a"),
                dst=P("test.b"),
                codec="json",
            ),
        )
        await c.i_sync()

        await sf.tg.start(run_gate, sf.cfg, c, "test")
        await c.i_sync()
        await anyio.sleep(0.2)

        a = await data_get(c, P("test.a"), out=False)
        assert a == dict(one={"_": 1}, two={"_": 2}, three={"_": 33})

        b = await backend_get(cc, P("test.b"), out=False)
        assert b == dict(one={"_": b"1"}, two={"_": b"22"}, three={"_": b"33"})

        # now change things
        await c.send(P("test.b.one"), 111, codec=codec, retain=True)
        await c.send(P("test.b.four"), 444, codec=codec, retain=True)
        await c.d_set(P("test.a.three"), 333)
        await c.d_set(P("test.a.five"), 555)
        await anyio.sleep(0.2)

        a = await data_get(c, P("test.a"), out=False)
        assert a == dict(
            one={"_": 111}, two={"_": 2}, three={"_": 333}, four={"_": 444}, five={"_": 555}
        )

        b = await backend_get(cc, P("test.b"), out=False)
        assert b == dict(
            one={"_": b"111"},
            two={"_": b"22"},
            three={"_": b"333"},
            four={"_": b"444"},
            five={"_": b"555"},
        )


@pytest.mark.trio
async def test_gate_kv(cfg, autojump_clock):  # noqa: D103
    autojump_clock.autojump_threshold = 0.4
    async with AsyncExitStack() as ex:
        sf = await ex.enter_async_context(Scaffold(cfg, use_servers=True))
        await sf.server(init={"Hello": "there!", "test": 123})

        cm = await sf.client()
        await sf.tg.start(mon, cm)

        URI = f"mqtt://127.0.0.1:{sf.cfg.backend.port}/"

        async def mock_get_host_port(kvs, host):  # noqa: ARG001
            return "127.0.0.1", sf.cfg.backend.port

        TESTCFG = copy.deepcopy(cfg.kv)
        TESTCFG.server.port = None
        TESTCFG.root = "test"

        clock = trio.lowlevel.current_clock()
        try:
            clock.autojump_threshold = 0.02  # networking
        except Exception:
            pass  # test doesn't have autojump_clock fixture
        kcfg = {
            "conn": {"ssl": False},
            "server": {
                "bind_default": {
                    "host": "127.0.0.1",
                    "port": 40000 + (sf.cfg.backend.port + 1) % 10000,
                    "ssl": False,
                },
                "backend": "mqtt",
                "mqtt": {"uri": URI},
            },
        }
        kcfg = to_attrdict(combine_dict(kcfg, TESTCFG))
        kvs = KVServer("KVgateTest", cfg=kcfg, init=dict(KV="test server"))
        ex.enter_context(
            mock.patch.object(kvs, "_get_host_port", new=partial(mock_get_host_port, kvs))
        )

        evt = anyio.Event()
        sf.tg.start_soon(partial(kvs.serve, ready_evt=evt))
        await evt.wait()

        for host, port, *_ in kvs.ports:
            if host != "::" and host[0] == ":":
                continue
            ccfg = combine_dict(
                dict(conn=dict(host="127.0.0.1", port=port, ssl=False)),
                cfg.kv,
            )
            kvc = await ex.enter_async_context(KVClient("test.client", **ccfg))
            break

        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()

        await c.d_set(P("test.a.one"), 1)
        await c.d_set(P("test.a.two"), 2)
        await kvc.set(P("test.b.two"), 22)
        await kvc.set(P("test.b.three"), 33)

        async def mon_src(task_status):
            async with c.d_watch(P("test.a")) as mon:
                got = []
                task_status.started(got)
                async for p, d in mon:
                    got.append((p, d))

        async def mon_dst(task_status):
            async with kvc.watch(P("test.b")) as mon:
                got = []
                task_status.started(got)
                async for m in mon:
                    got.append((m.path, m.value))

        await sf.tg.start(mon_src)
        await sf.tg.start(mon_dst)

        await c.d_set(
            P("gate.test"),
            dict(
                driver="kv",
                src=P("test.a"),
                dst=P("test.b"),
            ),
        )
        await c.i_sync()

        kcfg.conn = dict(host="127.0.0.1", port=kcfg.server.bind_default.port)
        await sf.tg.start(run_gate, dict(kv=kcfg), c, "test")

        await c.i_sync()
        a = await data_get(c, P("test.a"), out=False)
        assert a == dict(one={"_": 1}, two={"_": 2}, three={"_": 33})

        b = await kvdata_get(kvc, P("test.b"), out=False)
        assert b == dict(one={"_": 1}, two={"_": 2}, three={"_": 33})

        # now change things
        await kvc.set(P("test.b.one"), 111)
        await kvc.set(P("test.b.four"), 444)
        await kvc.set(P("test.b.two"), 22)
        await c.d_set(P("test.a.three"), 333)
        await c.d_set(P("test.a.five"), 555)
        await c.i_sync()
        await anyio.sleep(0.2)
        await c.i_sync()

        a = await data_get(c, P("test.a"), out=False)
        assert a == dict(
            one={"_": 111}, two={"_": 22}, three={"_": 333}, four={"_": 444}, five={"_": 555}
        )

        b = await kvdata_get(kvc, P("test.b"), out=False)
        assert b == dict(
            one={"_": 111}, two={"_": 22}, three={"_": 333}, four={"_": 444}, five={"_": 555}
        )


@pytest.mark.anyio
async def test_gate_codec(cfg):  # noqa: D103
    async with Scaffold(cfg, use_servers=True) as sf:
        # await sf.tg.start(_dump, sf)
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()
        cc = await sf.client()
        cm = await sf.client()
        await sf.tg.start(mon, cm)

        await c.d_set(
            P("codec.foo.bar"),
            dict(encode="return value.upper()\n", decode="return value.lower()\n"),
        )
        await c.d_set(P("conv.testing.baz.#.zaz"), dict(codec=P("foo.bar")))

        codec = get_codec("json")

        await c.d_set(P("test.a.baz.foo.bar.zaz"), "AbCd")
        await c.send(P("test.b.baz.quux.zaz"), "BcDe", retain=True)

        async def mon_src(task_status):
            async with c.d_watch(P("test.a")) as mon:
                got = []
                task_status.started(got)
                async for p, d in mon:
                    got.append((p, d))

        async def mon_dst(task_status):
            async with c.monitor(P("test.b"), codec=codec) as mon:
                got = []
                task_status.started(got)
                async for m in mon:
                    got.append((m.path, m.data))

        await sf.tg.start(mon_src)
        await sf.tg.start(mon_dst)

        await c.d_set(
            P("gate.tester"),
            dict(
                driver="mqtt",
                src=P("test.a"),
                dst=P("test.b"),
                codec=P("testing"),
            ),
        )
        await c.i_sync()

        await sf.tg.start(run_gate, sf.cfg, c, "tester")

        a = await data_get(c, P("test.a"), out=False)
        b = await backend_get(cc, P("test.b"), out=False)
        assert a == {
            "baz": {"foo": {"bar": {"zaz": {"_": "AbCd"}}}, "quux": {"zaz": {"_": "bcde"}}}
        }
        assert b == {
            "baz": {"foo": {"bar": {"zaz": {"_": "ABCD"}}}, "quux": {"zaz": {"_": "BcDe"}}}
        }

        # now change things
        await c.send(P("test.b.baz.one.two"), "OtWo", retain=True)
        await c.send(P("test.b.baz.one.two.zaz"), "OnE-tWo", retain=True)
        await c.send(P("test.b.baz.three.zaz"), "ThReE", retain=True)
        await c.send(P("test.b.baz.foo.bar.zaz"), "FuBaR", retain=True)
        await c.d_set(P("test.a.baz.four.five"), "FoVe")
        await c.d_set(P("test.a.baz.six.zaz"), "SiX")
        await c.d_set(P("test.a.baz.quux.zaz"), "QuuX")
        await anyio.sleep(0.2)

        a = await data_get(c, P("test.a"), out=False)
        b = await backend_get(cc, P("test.b"), out=False)
        assert a == {
            "baz": {
                "foo": {"bar": {"zaz": {"_": "fubar"}}},
                "four": {"five": {"_": "FoVe"}},
                "one": {"two": {"zaz": {"_": "one-two"}}},
                "quux": {"zaz": {"_": "QuuX"}},
                "six": {"zaz": {"_": "SiX"}},
                "three": {"zaz": {"_": "three"}},
            },
        }
        assert b == {
            "baz": {
                "foo": {"bar": {"zaz": {"_": "FuBaR"}}},
                "one": {"two": {"_": "OtWo", "zaz": {"_": "OnE-tWo"}}},
                "quux": {"zaz": {"_": "QUUX"}},
                "six": {"zaz": {"_": "SIX"}},
                "three": {"zaz": {"_": "ThReE"}},
            },
        }


class MockDelayedGate(DelayedGate):
    """
    A mock DelayedGate for testing that stores destination updates in a dict.
    """

    dst_store: dict
    dst_updates: list

    def __init__(self, cfg, cf, path, link):
        super().__init__(cfg, cf, path, link)
        self.dst_store = {}
        self.dst_updates = []

    async def get_dst(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        No external destination monitoring for this mock.
        """
        self.dst_is_current()
        task_status.started()
        # Keep running forever
        await anyio.sleep_forever()

    async def set_dst(self, path, data, meta, node):  # noqa: ARG002
        """
        Store destination updates in our dict.
        """
        self.dst_store[path] = data
        self.dst_updates.append((path, data, meta))

    def newer_dst(self, node):  # noqa: ARG002
        """
        For mock, just prefer source.
        """
        return False


@pytest.mark.anyio
async def test_delayed_gate_basic(cfg):
    """Test that DelayedGate delays updates by the configured time."""
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"test": 1})
        c = await sf.client()

        # Create gate config directly (no need to store in server)
        gate_cf = to_attrdict(
            dict(
                driver="mock",
                src=P("test.src"),
                delay=0.2,  # 200ms delay
            )
        )
        gate = MockDelayedGate(sf.cfg, gate_cf, P("gate.delayed"), c)

        async with anyio.create_task_group() as tg:
            await tg.start(gate.run)

            # Set source data
            await c.d_set(P("test.src.a"), 1)
            await c.d_set(P("test.src.b"), 2)

            # Updates should not appear immediately
            await anyio.sleep(0.05)
            assert P("a") not in gate.dst_store

            # Wait for delay to expire
            await anyio.sleep(0.25)
            assert gate.dst_store.get(P("a")) == 1
            assert gate.dst_store.get(P("b")) == 2

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_delayed_gate_cancellation(cfg):
    """Test that DelayedGate cancels pending updates when matching update arrives."""
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"test": 1})
        c = await sf.client()

        # Create gate config directly
        gate_cf = to_attrdict(
            dict(
                driver="mock",
                src=P("test.src"),
                delay=0.3,  # 300ms delay
            )
        )
        gate = MockDelayedGate(sf.cfg, gate_cf, P("gate.delayed"), c)

        async with anyio.create_task_group() as tg:
            await tg.start(gate.run)

            # Set source data
            await c.d_set(P("test.src.a"), 1)

            # Simulate an update from destination side before delay expires
            await anyio.sleep(0.1)
            # Call set_src directly to simulate incoming data from destination
            await gate.set_src(P("a"), 99, MsgMeta(origin="external"))

            # The set_src should have cancelled the pending dst update
            # Wait for delay to expire
            await anyio.sleep(0.4)

            # The original src->dst update for path "a" should have been cancelled
            # (because set_src cancels pending dst updates)
            # But set_src queues a src update, so we need to wait for that too

            # Check that the dst_store either doesn't have the value 1
            # (the original update was cancelled) or has 99 from set_src
            # In our mock, set_dst isn't called by set_src (it goes to link.d_set)
            # So dst_store should not have value 1 for path "a"
            assert gate.dst_store.get(P("a")) != 1

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_link_gate_sync(cfg):
    """
    Test Link gate synchronization between two servers.

    This tests that changes propagate bidirectionally via the link gate:
    1. Set up two servers on the same MQTT broker
    2. Create data on main server
    3. Start link gateway between the servers
    4. Verify data propagates to remote server
    5. Make changes on both sides while gateway is running
    6. Verify bidirectional synchronization
    """
    async with Scaffold(cfg, use_servers=True) as sf:
        # Start two servers
        await sf.server(init={"test": 1}, name="S_main")
        await sf.server(init={"test": 2}, name="S_remote")

        # Get client to main server (default)
        c_main = await sf.client()

        # Create initial data on main server
        await c_main.d_set(P("sync.a"), 1)
        await c_main.d_set(P("sync.b"), 2)
        await c_main.d_set(P("sync.c.d"), 3)

        # Connect to remote server
        async with Link(sf.cfg, only="S_remote") as c_remote:
            # Set some initial data on remote
            await c_remote.d_set(P("sync.x"), 100)

            # Start the link gate connecting main to remote
            gate_cf = to_attrdict(
                dict(
                    driver="link",
                    src=P("sync"),
                    server="S_remote",
                    delay=0.1,
                )
            )
            gate = LinkGate(sf.cfg, gate_cf, P("gate.sync"), c_main)

            async with anyio.create_task_group() as tg:
                await tg.start(gate.run)

                # Give time for initial sync
                await anyio.sleep(0.5)

                # Verify data propagated from main to remote
                res_remote = await c_remote.d_get(P("sync.a"))
                assert res_remote == 1, f"Main->Remote: sync.a = {res_remote}"

                res_remote = await c_remote.d_get(P("sync.b"))
                assert res_remote == 2, f"Main->Remote: sync.b = {res_remote}"

                # Verify sync.x propagated from remote to main
                res_main = await c_main.d_get(P("sync.x"))
                assert res_main == 100, f"Remote->Main: sync.x = {res_main}"

                # Make changes on both sides while gateway is running
                await c_main.d_set(P("sync.new_main"), 999)
                await c_remote.d_set(P("sync.new_remote"), 888)

                # Wait for sync
                await anyio.sleep(0.5)

                # Verify bidirectional propagation
                res_main = await c_main.d_get(P("sync.new_remote"))
                assert res_main == 888, f"Remote->Main: sync.new_remote = {res_main}"

                res_remote = await c_remote.d_get(P("sync.new_main"))
                assert res_remote == 999, f"Main->Remote: sync.new_main = {res_remote}"

                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_gate_speed(cfg):
    """
    Test the speed-limiting feature: rapid external updates are coalesced
    into a single delayed entry and the last value wins.

    The ``speed`` config key sets a minimum interval between source updates.
    When a new external value arrives for a path whose MoaT-Link entry is
    fresher than ``speed`` seconds, the update is held in a TimerMap.
    If another update for the same path arrives before the timer fires,
    the pending entry is updated in-place so only one write eventually
    reaches MoaT-Link – with the most-recent value.

    After the timer fires (or is forced in this test), a second rapid
    update verifies that the freshly-written timestamp re-arms the
    rate-limiter.
    """
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"test": 1})
        c = await sf.client()

        # Establish an initial value so get_src can set node.meta
        await c.d_set(P("test.src.val"), 0)
        await c.i_sync()

        gate_cf = to_attrdict(
            dict(
                driver="mock",
                src=P("test.src"),
                speed=5.0,  # large window – always in range during the test
            )
        )
        gate = MockDelayedGate(sf.cfg, gate_cf, P("gate.speed_test"), c)

        async with anyio.create_task_group() as tg:
            await tg.start(gate.run)

            # After the gate has synced, node.meta must be set and fresh.
            node = cast(GateNode, gate.data.get(P("val")))
            assert node.meta is not None, "node.meta should be set after initial sync"
            assert time.time() - node.meta.timestamp < gate._speed, (  # noqa: SLF001
                "test assumption: node.meta.timestamp is within the speed window"
            )

            meta_ext = MsgMeta(origin="external")

            # ── Phase 1: coalescing ───────────────────────────────────────
            # Two rapid updates → only ONE entry in _waiting.
            await gate.set_src(P("val"), 10, meta_ext)
            assert len(gate._waiting) == 1, "first rapid update should be queued"  # noqa: SLF001

            await gate.set_src(P("val"), 20, meta_ext)
            assert len(gate._waiting) == 1, "second rapid update should coalesce, not duplicate"  # noqa: SLF001

            # Force the pending timer to fire immediately.
            pending_key, _ = gate._waiting.pop()  # noqa: SLF001
            gate._waiting[pending_key] = 0  # re-insert with zero delay  # noqa: SLF001

            await anyio.sleep(0.1)  # let _process_pending fire

            val = await c.d_get(P("test.src.val"))
            assert val == 20, f"last coalesced value (20) should be written, got {val!r}"

            # ── Phase 2: re-arm after timer fires ────────────────────────
            # _process_pending updates node.meta with a fresh timestamp, so
            # the next rapid update is delayed again rather than applied
            # immediately.
            assert len(gate._waiting) == 0, "no pending entries after first fire"  # noqa: SLF001

            await gate.set_src(P("val"), 30, meta_ext)
            assert len(gate._waiting) == 1, (  # noqa: SLF001
                "update right after a write should be speed-limited again"
            )

            # Force that timer too and verify the value lands.
            pending_key2, _ = gate._waiting.pop()  # noqa: SLF001
            gate._waiting[pending_key2] = 0  # noqa: SLF001

            await anyio.sleep(0.1)

            val = await c.d_get(P("test.src.val"))
            assert val == 30, f"re-armed speed limit: expected 30, got {val!r}"

            tg.cancel_scope.cancel()
