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
from copy import deepcopy
from functools import partial

from asyncowfs.mock import some_server, structs

import moat.link.ow  # noqa:F401 - register cfg
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


async def _run_mock_ow(link, cfg_ow, name, tree, *, task_status):
    """Serve a mock owserver and run the connector task for one server."""
    async with await anyio.create_tcp_listener(
        local_host="127.0.0.1",
        local_port=0,
        reuse_port=True,
    ) as listener:
        addr = listener.extra(anyio.abc.SocketAttribute.raw_socket).getsockname()
        port = addr[1]

        prefix = Path.build(cfg_ow["prefix"])
        await link.d_set(prefix / name, {"server": {"host": "127.0.0.1", "port": port}})
        await link.i_sync()

        async with anyio.create_task_group() as tg:

            async def serve():
                with contextlib.suppress(anyio.ClosedResourceError, anyio.BrokenResourceError):
                    await listener.serve(partial(some_server, tree, {}))

            tg.start_soon(serve)
            await task(link, cfg_ow, name, task_status=task_status)


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
        await sf.tg.start(_run_mock_ow, c, cfg.link.ow, "g1", my_tree)

        # configure mirroring (small intervals for a fast test)
        await sf.run(
            "link ow g1 at 10.345678.90 temperature add -s dest .data.temp -s interval =0.5"
        )
        await sf.run("link ow g1 at 10.345678.90 templow add -w -s src .data.low")
        await sf.run("link ow g1 at 10.345678.90 foo.bar add -w -s src .data.what.ever -a bar:1")
        await sf.run(
            "link ow g1 at 10.345678.90 foo.plugh:1 add -s dest .data.this -s interval =0.5 -a baz:2"
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
