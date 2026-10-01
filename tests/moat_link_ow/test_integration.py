"""End-to-end test for ``moat.link.ow`` mirroring.

Boots a mock owserver (via ``asyncowfs.mock``), runs the connector
task against it, configures attribute mappings through the CLI, and
checks that values are mirrored in both directions.
"""

from __future__ import annotations

import anyio
import contextlib
import logging
import pytest
import socket
from copy import deepcopy
from functools import partial

from asyncowfs.mock import some_server, structs

import moat.link.ow  # noqa:F401 - register cfg
from moat.util import ungroup
from moat.lib.path import P, Path
from moat.link._test import Scaffold
from moat.link.ow.task import task

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.anyio

basic_tree = {
    "bus.0": {
        "alarm": {},
        "simultaneous": {"temperature": 0},
        "10.345678.90": {
            "latesttemp": "12.5",
            "temperature": "12.5",
            "templow": "15",
            "temphigh": "20",
            "foo": {"bar": 123, "plugh.A": 1, "plugh.B": 2, "plugh.C": 3},
        },
    },
    "structure": structs,
}


async def _mock_ow(link, cfg, name, tree, *, scan=None, task_status):
    """Serve a mock owserver and register it as server @name."""
    async with await anyio.create_tcp_listener(
        local_host="127.0.0.1",
        local_port=0,
        reuse_port=True,
    ) as listener:
        addr = listener.extra(anyio.abc.SocketAttribute.raw_socket).getsockname()
        srv = {"host": "127.0.0.1", "port": addr[1]}
        if scan is not None:
            srv["scan"] = scan

        prefix = Path.build(cfg.link.ow.prefix)
        await link.d_set(prefix / "server" / name, {"server": srv})
        await link.i_sync()

        with contextlib.suppress(anyio.ClosedResourceError, anyio.BrokenResourceError):
            task_status.started()
            await listener.serve(partial(some_server, tree, {}))


async def _run_mock_ow(link, cfg, name, tree, *, task_status):
    """Serve a mock owserver and run the connector."""
    async with anyio.create_task_group() as tg:
        await tg.start(_mock_ow, link, cfg, name, tree)
        await task(link, cfg, task_status=task_status)


async def _expect_link(c, path, want, timeout=5.0):
    """Wait until ``path`` holds ``want`` in MoaT-Link."""
    deadline = anyio.current_time() + timeout
    last = None
    while anyio.current_time() < deadline:
        try:
            last = await c.d_get(path)
        except KeyError:
            last = None
        if last == want:
            return
        await anyio.sleep(0.1)
    raise AssertionError(f"{path}: wanted {want!r}, got {last!r}")


async def _expect_tree(dt, keys, want, timeout=5.0):
    """Wait until ``dt[keys…]`` equals ``want`` in the mock owserver tree."""
    deadline = anyio.current_time() + timeout
    last = None
    while anyio.current_time() < deadline:
        cur = dt
        try:
            for k in keys:
                cur = cur[k]
        except (KeyError, TypeError):
            cur = None
        last = cur
        if cur == want:
            return
        await anyio.sleep(0.1)
    raise AssertionError(f"{keys}: wanted {want!r}, got {last!r}")


async def test_mirror(cfg):
    """Read and write mirroring between 1-Wire and MoaT-Link."""
    my_tree = deepcopy(basic_tree)
    dt = my_tree["bus.0"]["10.345678.90"]

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await sf.tg.start(_run_mock_ow, c, cfg, "g1", my_tree)

        # configure mirroring (small intervals for a fast test)
        await sf.run("link ow at 10.345678.temperature add -s dest .data.temp -s interval =0.5")
        await sf.run("link ow at 10.345678.templow add -w -s src .data.low")
        await sf.run("link ow at 10.345678.foo.bar add -w -s src .data.what.ever -a bar:1")
        await sf.run(
            "link ow at 10.345678.foo.plugh:1 add -s dest .data.this -s interval =0.5 -a baz:2"
        )
        await c.i_sync()

        # seed the merge target
        await c.d_set(P("data.this"), {"this": "is", "baz": {3: 33}})

        # read direction: temperature is polled into .data.temp
        await _expect_link(c, P("data.temp"), 12.5)

        # write direction: setting sources writes onto the bus
        await c.d_set(P("data.low"), 11)
        await c.d_set(P("data.what.ever"), {"Hello": "No", "bar": {0: 99, 1: 13}})
        await _expect_tree(dt, ("templow",), "11")
        await _expect_tree(dt, ("foo", "bar"), "13")

        # change mock values; polling picks them up
        dt["latesttemp"] = "42"
        dt["temperature"] = "42"
        dt["foo"]["plugh.B"] = "22"

        await _expect_link(c, P("data.temp"), 42)
        await _expect_link(c, P("data.this"), {"this": "is", "baz": {2: 22, 3: 33}})


async def test_move(cfg):
    """A device that moves to another bus keeps being mirrored."""
    tree_a = deepcopy(basic_tree)
    tree_b = deepcopy(basic_tree)
    dev = tree_b["bus.0"].pop("10.345678.90")

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await sf.run("link ow at 10.345678.temperature add -s dest .data.temp -i 0.3")
        await sf.run("link ow at 10.345678.templow add -w -s src .data.low")
        await c.i_sync()

        await sf.tg.start(partial(_mock_ow, scan=1), c, cfg, "a", tree_a)
        await sf.tg.start(partial(_mock_ow, scan=1), c, cfg, "b", tree_b)
        await sf.tg.start(task, c, cfg)

        await _expect_link(c, P("data.temp"), 12.5)
        await c.d_set(P("data.low"), 11)
        await _expect_tree(tree_a["bus.0"]["10.345678.90"], ("templow",), "11")

        # move the device from bus a to bus b
        del tree_a["bus.0"]["10.345678.90"]
        dev["temperature"] = "33"
        tree_b["bus.0"]["10.345678.90"] = dev

        await _expect_link(c, P("data.temp"), 33)
        # the writer is restarted on the new bus
        await c.d_set(P("data.low"), 9)
        await _expect_tree(dev, ("templow",), "9")


def _closed_port() -> int:
    "A local port that nobody listens on."
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _expect_error(c, path, text, timeout=5.0):
    "Wait until an error containing @text is reported at @path."
    with anyio.fail_after(timeout):
        async with c.d_watch(P("error") + path, subtree=True, state=None) as mon:
            async for _p, d in mon:
                if text in str(d):
                    return


def _fast_retry(cfg):
    cfg.link.gate.backoff = dict(min=0.2, max=0.3, factor=2)
    cfg.link.gate.recovery = 0.3


@pytest.mark.parametrize("crash", [False, True])
async def test_refused(cfg, crash):
    "A server that refuses connections is reported and retried, in both modes."
    _fast_retry(cfg)
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = Path.build(cfg.link.ow.prefix)
        await c.d_set(
            prefix / "server" / "bad", {"server": {"host": "127.0.0.1", "port": _closed_port()}}
        )
        await c.i_sync()

        await sf.tg.start(partial(task, crash=crash), c, cfg)
        await _expect_error(c, prefix / "server" / "bad", "connect")
        # still running (a crash would end the scaffold), still retrying
        await anyio.sleep(1)


@pytest.mark.parametrize("crash", [False, True])
async def test_crash(cfg, crash, monkeypatch):
    "Other errors are retried by the shared monitor, but end a single-server one."
    from asyncowfs.service import Service  # noqa: PLC0415

    _fast_retry(cfg)
    calls = 0
    retried = anyio.Event()

    async def add_server(_self, *_a, **_kw):
        nonlocal calls
        calls += 1
        if calls >= 3:
            retried.set()
        raise RuntimeError("boom")

    monkeypatch.setattr(Service, "add_server", add_server)
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = Path.build(cfg.link.ow.prefix)
        await c.d_set(prefix / "server" / "s", {"server": {"host": "127.0.0.1"}})
        await c.i_sync()

        if crash:
            with pytest.raises(RuntimeError, match="boom"), ungroup, anyio.fail_after(5):
                await task(c, cfg, ("s",), crash=True)
            assert calls == 1
        else:
            await sf.tg.start(task, c, cfg)
            await _expect_error(c, prefix / "server" / "s", "boom")
            with anyio.fail_after(5):
                await retried.wait()


async def test_mapping_error(cfg):
    "A mapping that doesn't work is reported at its path."
    my_tree = deepcopy(basic_tree)

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await sf.tg.start(_run_mock_ow, c, cfg, "g1", my_tree)
        await sf.run("link ow at 10.345678.nonexistent add -s dest .data.x -i 0.5")
        prefix = Path.build(cfg.link.ow.prefix)
        await _expect_error(c, prefix / 0x10 / 0x345678 / "nonexistent", "nonexistent")
