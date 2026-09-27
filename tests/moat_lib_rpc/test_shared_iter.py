"""Tests for the shared iterator multiplexing in BaseCmdMsg."""

from __future__ import annotations

import anyio
import pytest

from moat.lib.micro import sleep_ms
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack

pytestmark = pytest.mark.anyio

# Config: a self-linked BaseCmdMsg (LoopCmd) alongside a test Cmd with
# a streaming iterator (stream_it).  The LoopCmd's loopback goes back to
# the same root, so ``b.mon_("a.it")`` calls ``a.it`` through the wire
# and fans out the result to subscribers.

CFG = """
app: dir
a:
  app: _test_.Cmd
b:
  app: _test.LoopCmd
  link:
    pack: cbor
"""


async def test_shared_iter_single(tmp_path):
    """A single subscriber receives all data from the remote iterator."""
    async with rpc_stack(tmp_path, CFG) as d:
        b = d.sub_at(P("b"))
        await b.cmd(P("rdy_"))

        collected: list[int] = []
        async with b.cmd(P("mon_"), P("a.it"), lim=5, delay=0.01).stream_in() as st:
            async for data in st:
                collected.append(data[0])

        assert collected == [0, 1, 2, 3, 4]


async def test_shared_iter_multi(tmp_path):
    """Multiple subscribers receive the same data from one remote iterator."""
    async with rpc_stack(tmp_path, CFG) as d:
        b = d.sub_at(P("b"))
        await b.cmd(P("rdy_"))

        results_a: list[int] = []
        results_b: list[int] = []

        async def subscriber(res: list[int]):
            # 20 items, 50 ms apart: the stream is still running when the
            # second subscriber joins, even on a busy machine
            async with b.cmd(P("mon_"), P("a.it"), lim=20, delay=0.05).stream_in() as st:
                async for data in st:
                    res.append(data[0])

        async with anyio.create_task_group() as tg:
            tg.start_soon(subscriber, results_a)
            await sleep_ms(50)
            tg.start_soon(subscriber, results_b)

        # Both subscribers should have received the same data.
        assert results_a == list(range(20))
        # Second subscriber joined after a delay, so it may have missed
        # early items, but should have received the later ones.
        assert len(results_b) > 0
        assert results_a[-len(results_b) :] == results_b


async def test_shared_iter_reuse(tmp_path):
    """After all subscribers leave, a new subscriber opens a fresh stream."""
    async with rpc_stack(tmp_path, CFG) as d:
        b = d.sub_at(P("b"))
        await b.cmd(P("rdy_"))

        collected1: list[int] = []
        async with b.cmd(P("mon_"), P("a.it"), lim=3, delay=0.01).stream_in() as st:
            async for data in st:
                collected1.append(data[0])
        assert collected1 == [0, 1, 2]

        await sleep_ms(50)

        collected2: list[int] = []
        async with b.cmd(P("mon_"), P("a.it"), lim=3, delay=0.01).stream_in() as st:
            async for data in st:
                collected2.append(data[0])
        assert collected2 == [0, 1, 2]
