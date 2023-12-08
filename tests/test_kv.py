import logging
from time import time

import asyncclick as click
import pytest
import trio
import os
from moat.src.test import raises
from moat.util import P, PathLongener, yload

from moat.kv.client import ServerError
from moat.kv.mock.mqtt import stdtest
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

@pytest.mark.trio
async def test_kv_poll(autojump_clock):  # pylint: disable=unused-argument
    cfg1 = yload(cfg1_, attr=True)
    cfg2 = yload(cfg2_, attr=True)
    PORT = 40000 + (os.getpid() + 20) % 10000
    cfg1.server[0].port = PORT
    cfg2.hostports.localhost[PORT] = cfg2.hostports.localhost.PORT
    del cfg2.hostports.localhost.PORT

    async with (
            stdtest(args={"init": 123}, tocks=50) as st,
            st.client() as c,
            trio.open_nursery() as tg,
        ):
        assert (await c.get(P(":"))).value == 123
        await c.set(P("a.srv.src"), value=42)
        cfg1 = await tg.start(dev_poll, cfg1, c)
        reg = cfg1.server[0].units[32].regs.no_question
        await trio.sleep(1)
        assert reg.value_w == 42

        await c.set(P("a.srv.src"), value=44)
        await trio.sleep(1)
        assert reg.value_w == 44

        breakpoint()
        reg.set(43)
        await trio.sleep(2)

        rv = await c.get(P("a.srv.dst"))
        assert rv == 43
        assert reg.value_w == 44
        assert reg.value == 43

        async with (
            ModbusClient() as g,
            g.host("localhost", PORT) as h,
            h.unit(32) as u,
            u.slot("default") as s,
        ):
            v = s.add(HoldingRegisters, 12342, IntValue)
            res = await s._getValues()
            breakpoint()
            pass # v,res


        pass # ex



