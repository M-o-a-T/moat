"""
Tests for what `moat.modbus.dev.poll.dev_poll` tells MoaT-Link: poll
failures, and its service announcement.
"""

from __future__ import annotations

import anyio
import platform
import pytest
import socket
from functools import partial

from moat.util import yload
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.modbus.dev.poll import dev_poll

from typing import Any

CFG = """
slots:
  1sec:
    read_delay: 1
hostports:
  127.0.0.1:
    {port}:
      timeout: {timeout}
      1:
        regs:
          r: {{reg_type: h, register: 1, type: uint, len: 1, slot: 1sec, dest: !P test.r}}
"""

ERR = P("error.app.modbus.tcp") / "127.0.0.1"


def _dead_port() -> int:
    "a port nobody listens on"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_err(c: Any, path: P, limit: float) -> Any:
    "wait for an item (e.g. an error record) at @path; fail after @limit seconds"
    with anyio.fail_after(limit):
        while True:
            try:
                return await c.d_get(path)
            except KeyError:
                await anyio.sleep(0.2)


@pytest.mark.anyio
async def test_unreachable(cfg):  # noqa: ARG001
    "an unreachable host is reported at its host path"
    async with (
        Scaffold(True, use_servers=True) as sf,
        sf.server_(init={"x": 1}),
        sf.client_() as c,
        anyio.create_task_group() as tg,
    ):
        port = _dead_port()
        await tg.start(dev_poll, yload(CFG.format(port=port, timeout=10), attr=True), c)
        err = await _wait_err(c, ERR / str(port), 5)
        assert "exc" in err
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_unresponsive_timeout(cfg):  # noqa: ARG001
    "a host that doesn't answer is reported at the slot, after the configured timeout"
    async with (
        Scaffold(True, use_servers=True) as sf,
        sf.server_(init={"x": 1}),
        sf.client_() as c,
        anyio.create_task_group() as tg,
    ):
        lst = await anyio.create_tcp_listener(local_host="127.0.0.1", local_port=0)
        port = lst.extra(anyio.abc.SocketAttribute.local_port)

        async def handle(conn: Any) -> None:
            async with conn:
                await anyio.sleep_forever()

        tg.start_soon(lst.serve, handle)
        await tg.start(dev_poll, yload(CFG.format(port=port, timeout=1), attr=True), c)
        # the default timeout is 10 seconds
        err = await _wait_err(c, ERR / str(port) / "1" / "1sec", 4)
        assert "exc" in err
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_announce(cfg, monkeypatch):  # noqa: ARG001
    "the poller announces itself while it runs"
    monkeypatch.setenv("MT_SERVICE", "test.poller")
    path = P("run.host") / platform.node() / "test" / "poller"
    async with (
        Scaffold(True, use_servers=True) as sf,
        sf.server_(init={"x": 1}),
        sf.client_() as c,
    ):
        async with anyio.create_task_group() as tg:
            await tg.start(
                partial(dev_poll, announce=True),
                yload("server: [{host: 127.0.0.1, port: 0}]", attr=True),
                c,
            )
            await c.i_sync()
            ann = await _wait_err(c, path, 5)
            with anyio.fail_after(5):
                while not ann.get("up"):
                    await anyio.sleep(0.1)
                    ann = await c.d_get(path)
            tg.cancel_scope.cancel()
        with anyio.fail_after(5):
            while True:
                try:
                    await c.d_get(path)
                except KeyError:
                    break
                await anyio.sleep(0.1)


@pytest.mark.anyio
async def test_refresh(cfg):  # noqa: ARG001
    "a steady value is sent again, so its timestamp shows that it's current"
    from moat.modbus.server import UnitContext, create_server  # noqa: PLC0415
    from moat.modbus.types import HoldingRegisters, IntValue  # noqa: PLC0415

    async with (
        Scaffold(True, use_servers=True) as sf,
        sf.server_(init={"x": 1}),
        sf.client_() as c,
        anyio.create_task_group() as tg,
    ):
        dev = create_server({"host": "127.0.0.1", "port": 0})
        ctx = UnitContext()
        dev.add_unit(1, ctx)
        ctx.add(HoldingRegisters, 1, IntValue).value = 42
        evt = anyio.Event()
        tg.start_soon(partial(dev.serve, opened=evt))
        await evt.wait()

        cfg_ = yload(
            f"""
slots:
  1sec:
    read_delay: 0.2
hostports:
  127.0.0.1:
    {dev.port}:
      1:
        regs:
          r: {{reg_type: h, register: 1, type: uint, len: 1, slot: 1sec, dest: !P test.r, idem: 1}}
""",
            attr=True,
        )
        await tg.start(dev_poll, cfg_, c)
        await _wait_err(c, P("test.r"), 5)
        _, m1 = await c.d_get(P("test.r"), meta=True)
        with anyio.fail_after(5):
            while True:
                await anyio.sleep(0.2)
                v, m2 = await c.d_get(P("test.r"), meta=True)
                if m2.timestamp > m1.timestamp:
                    break
        assert v == 42
        assert m2.timestamp - m1.timestamp < 2
        tg.cancel_scope.cancel()
