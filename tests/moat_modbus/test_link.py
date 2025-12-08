from __future__ import annotations  # noqa: D100

import logging
import pytest

import trio

from moat.util import P, yload
from moat.link._test import Scaffold
from moat.modbus.client import ModbusClient
from moat.modbus.dev.poll import dev_poll
from moat.modbus.types import HoldingRegisters, IntValue

_lg = logging.getLogger("moat.mqtt.mqtt.protocol.handler")
_lg.level = logging.WARNING

_lg = logging.getLogger("moat.kv.server.test_0")
_lg.level = logging.WARNING

logger = logging.getLogger(__name__)

cfg1_ = """
server:
- host: 127.0.0.1
  port: -1
  units:
    32:
      regs:
        no_question:
          reg_type: h
          register: 12342
          dest: !P a.srv.dst
          src: !P a.srv.src
          type: uint
          len: 1
"""

cfg2_ = """
slots:
  1sec:
    read_delay: 1
    write_delay: 1
    read_align: false
hostports:
  localhost:
    PORT:
      32:
        regs:
          the_answer:
            reg_type: h
            register: 12342
            type: uint
            len: 1
            dest: !P a.cli.dst
            src: !P a.cli.src
            slot: 1sec


"""


async def mon(c):  # noqa: D103
    async with c.monitor(P(":"), codec="std-cbor", subtree=True) as mo:
        async for msg in mo:
            print("*****", msg)


@pytest.mark.trio
async def test_kv_poll(cfg, autojump_clock, free_tcp_port):  # noqa: D103
    cfg  # noqa:B018
    autojump_clock.autojump_threshold = 0.2
    cfg1 = yload(cfg1_, attr=True)
    cfg2 = yload(cfg2_, attr=True)
    cfg1.server[0].port = free_tcp_port
    cfg2.hostports.localhost[free_tcp_port] = cfg2.hostports.localhost.PORT
    del cfg2.hostports.localhost.PORT

    from moat.util import CFG  # noqa: PLC0415

    cfg = CFG.result

    async with (
        Scaffold(True, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "value": 123}),
        sf.client_() as c,
        trio.open_nursery() as tg,
    ):
        # tg.start_soon(mon,c)
        r = await c.d_get(P(":"))
        assert r["value"] == 123
        assert (await c.d_get(P(":")))["value"] == 123
        await c.d_set(P("a.srv.src"), data=42)
        await c.i_sync()
        cfg1 = await tg.start(dev_poll, cfg1, c)
        reg = cfg1.server[0].units[32].regs.no_question
        await trio.sleep(1)
        assert reg.value_w == 42

        await c.d_set(P("a.srv.src"), data=50044)
        await trio.sleep(2)
        assert reg.value_w == 50044

        await c.d_set(P("a.cli.src"), data=144)
        cfg2 = await tg.start(dev_poll, cfg2, c)
        await trio.sleep(2)

        # bidirectional forwarding

        await c.i_sync()
        try:
            rv = await c.d_get(P("a.cli.dst"))
        except KeyError:
            rv = None
        assert rv == 50044

        try:
            rv = await c.d_get(P("a.srv.dst"))
        except KeyError:
            rv = None
        assert rv == 144

        # explicit read

        async with (
            ModbusClient() as g,
            g.host("localhost", free_tcp_port) as h,
            h.unit(32) as u,
            u.slot("default") as s,
        ):
            s.add(HoldingRegisters, 12342, IntValue)
            res = await s.getValues()
            assert res[HoldingRegisters][12342].value == 50044

        # terminate tasks
        tg.cancel_scope.cancel()
