"""
Tests for switchable server-unit bypass (``bypass:`` in `moat.modbus.dev.poll`).

A fake Modbus device C; a poller B that polls C and serves it as unit 3, with a
bypass to C itself; a shim A that serves unit 101 from MoaT-Link data,
with a bypass to B's unit 3.
"""

from __future__ import annotations

import anyio
import pytest
import socket
from functools import partial

import trio

from moat.util import yload
from moat.lib.modbus import ExcCodes, ExceptionResponse
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.modbus.client import ModbusClient
from moat.modbus.dev.poll import dev_poll
from moat.modbus.server import UnitContext, create_server
from moat.modbus.types import HoldingRegisters, IntValue
from moat.src.test import raises

from typing import Any


class DevCtx(UnitContext):
    "the fake device: registers at or above 300 don't exist"

    def get_values(self, kind: str, address: int, count: int) -> list[int]:  # noqa: D102
        if address >= 300:
            raise KeyError(address)
        return super().get_values(kind, address, count)


POLLER = """
slots:
  normal:
    read_delay: 100
  write:
    write_delay: 0.1
server:
  - host: 127.0.0.1
    port: 0
hostports:
  localhost:
    {port}:
      1:
        server: 3
        bypass:
          when: !P test.bp_b
        regs:
          polled: {{reg_type: h, register: 100, type: uint, len: 1, slot: normal}}
          cmd: {{reg_type: h, register: 200, type: uint, len: 1, src: !P test.cmd}}
"""

SHIM = """
server:
  - host: 127.0.0.1
    port: 0
    units:
      101:
        bypass:
          when: [!P test.pt, !P bypass]
          dest: {{host: localhost, port: {port}, unit: 3}}
        regs:
          polled: {{reg_type: h, register: 100, type: uint, len: 1, src: !P test.fake}}
      102:
        bypass:
          when: [!P test.pt, !P bypass]
          dest: {{host: localhost, port: {dead}, unit: 3}}
        regs:
          polled: {{reg_type: h, register: 100, type: uint, len: 1, src: !P test.fake}}
"""


def _dead_port() -> int:
    "a port nobody listens on"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _read(u: Any, addr: int) -> int | ExcCodes:
    "read one holding register; the value, or the exception code"
    res = await u.process_request(HoldingRegisters.encoder(address=addr, count=1, unit_id=u.unit))
    if isinstance(res, ExceptionResponse):
        return ExcCodes(res.exception_code)
    return res.registers[0]


async def _write(u: Any, addr: int, val: int) -> None:
    "write one holding register"
    res = await u.process_request(
        HoldingRegisters.encoder_s(address=addr, unit_id=u.unit, registers=[val])
    )
    assert not isinstance(res, ExceptionResponse), res


@pytest.mark.trio
async def test_bypass(cfg, autojump_clock, monkeypatch):  # noqa: ARG001
    "bypass off: served locally; on: both hops pass everything through"
    autojump_clock.autojump_threshold = 0.05
    monkeypatch.setattr("anyio.current_time", trio.current_time)

    async with (
        anyio.create_task_group() as tg,
        Scaffold(True, use_servers=True) as sf,
        sf.server_(init={"test": "data"}),
        sf.client_() as c,
    ):
        await c.d_set(P("test.fake"), 5)
        await c.d_set(P("test.pt"), {"bypass": False, "switching": None})
        await c.d_set(P("test.bp_b"), False)
        await c.i_sync()

        dev = create_server({"host": "127.0.0.1", "port": 0})
        ctx = DevCtx()
        dev.add_unit(1, ctx)
        polled = ctx.add(HoldingRegisters, 100, IntValue)
        ctx.add(HoldingRegisters, 101, IntValue).value = 7
        ctx.add(HoldingRegisters, 150, IntValue)
        ctx.add(HoldingRegisters, 200, IntValue)
        polled.value = 100
        evt = anyio.Event()
        tg.start_soon(partial(dev.serve, opened=evt))
        await evt.wait()
        dev_port = dev.port

        poller = await tg.start(dev_poll, yload(POLLER.format(port=dev_port), attr=True), c)
        b_port = poller.server[0].port
        shim = await tg.start(
            dev_poll,
            yload(SHIM.format(port=b_port, dead=_dead_port()), attr=True),
            c,
        )
        a_port = shim.server[0].port
        await anyio.sleep(1)

        async def flags(pt: bool, bp_b: bool) -> None:
            await c.d_set(P("test.pt"), {"bypass": pt, "switching": None})
            await c.d_set(P("test.bp_b"), bp_b)
            await c.i_sync()
            await anyio.sleep(0.5)

        async with (
            ModbusClient() as cli,
            cli.host("localhost", a_port) as ha,
            cli.host("localhost", b_port) as hb,
            cli.host("localhost", dev_port) as hc,
        ):
            a, a_dead, b, dev_u = ha.unit(101), ha.unit(102), hb.unit(3), hc.unit(1)

            # off: the shim serves Link data, the poller its cache
            assert await _read(a, 100) == 5
            assert await _read(b, 100) == 100
            polled.value = 111
            assert await _read(b, 100) == 100

            # on: live data, including registers nobody polls
            await flags(True, True)
            assert await _read(a, 100) == 111
            assert await _read(b, 100) == 111
            assert await _read(a, 101) == 7

            # writes reach the device
            await _write(a, 150, 42)
            assert await _read(dev_u, 150) == 42

            # the device's exceptions come back unchanged
            assert await _read(dev_u, 300) == ExcCodes.ILLEGAL_DATA_ADDRESS
            assert await _read(a, 300) == ExcCodes.ILLEGAL_DATA_ADDRESS

            # an unreachable target
            assert await _read(a_dead, 100) == ExcCodes.GATEWAY_TARGET_NO_RESPONSE

            # the poller's own writes pause while bypassed …
            await c.d_set(P("test.cmd"), 9)
            await c.i_sync()
            await anyio.sleep(3)
            assert await _read(dev_u, 200) == 0

            # … and resume afterwards; the shim is local again
            await flags(False, False)
            await anyio.sleep(3)
            assert await _read(dev_u, 200) == 9
            assert await _read(a, 100) == 5

        tg.cancel_scope.cancel()


@pytest.mark.trio
async def test_bypass_needs_dest(cfg, autojump_clock):  # noqa: ARG001
    "a server unit's bypass without dest is rejected"
    autojump_clock.autojump_threshold = 0.05
    bad = yload(
        """
server:
  - host: 127.0.0.1
    port: 0
    units:
      1:
        bypass:
          when: !P test.x
        regs:
          r: {reg_type: h, register: 1, type: uint, len: 1}
""",
        attr=True,
    )
    with raises(ValueError):
        async with anyio.create_task_group() as tg:
            await tg.start(dev_poll, bad, None)
