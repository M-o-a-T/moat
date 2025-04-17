from __future__ import annotations

import pytest

from moat.link.meta import MsgMeta
from moat.link._test import Scaffold
from moat.link.node import Node
from moat.util import P, PathLongener, NotGiven, ungroup
from moat.util.msg import MsgReader
from moat.lib.cmd import StreamError
from moat.lib.codec.cbor import Tag as CBORTag
from moat.util.cbor import CBOR_TAG_MOAT_FILE_ID, CBOR_TAG_MOAT_FILE_END
from moat.link.client import BasicLink

import logging

logger = logging.getLogger(__name__)


async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    async with bk.monitor(P("#"), qos=0) as mon:
        task_status.started()
        async for msg in mon:
            print(msg)


async def data(s):
    await s("a.b.e", 10)
    await s("a.b.f", 11)
    await s("a.b.g.h", 12)
    await s("a.b.g.o", 121)
    await s("a.b.i", 13)
    await s("a.b.j", 14)
    await s("a.c", 15)
    await s("a.c.d", 16)
    await s("a.b.d", 17)


async def fetch(c, p):
    p = P(p)
    nn = Node()
    pl = PathLongener()
    async with c.cmd(P("d.walk"), p).stream_in() as msgs:
        try:
            it = aiter(msgs)
        except StreamError as exc:
            try:
                if exc.args[0][0] == "KeyError":
                    return nn  # empty
            except Exception:
                pass
            raise exc from None

        async for pr, p, d, *m in it:
            p = pl.long(pr, p)
            nn.set(p, d, MsgMeta._moat__restore(m, NotGiven))
        return nn


@pytest.mark.anyio()
async def test_lsy_from_server(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})
        c1 = await sf.client()
        n = Node()

        async def s(p, v):
            p = P(p)
            await c1.cmd(P("d.set"), p, v)
            n.set(p, v, MsgMeta(origin="Test"))

        await data(s)

        await sf.server()
        if c1._link._last_link is None:
            await c1._link._last_link_seen.wait()

        async with BasicLink(cfg, "c_test", c1._link._last_link.data) as c2:
            nn = await fetch(c2, "a")

            assert n.get(P("a")) == nn


@pytest.mark.anyio()
async def test_lsy_from_file(cfg, tmp_path):
    async with Scaffold(cfg, use_servers=True, tempdir=tmp_path) as sf:
        (sf.tempdir / "data").mkdir()

        srv1 = await sf.server(init={"Hello": "there!", "test": 123})
        c1 = await sf.client()
        n = Node()

        async def s(p, v):
            p = P(p)
            await c1.cmd(P("d.set"), p, v)
            n.set(p, v, MsgMeta(origin="Test"))

        await data(s)
        fn = next(iter(srv1[0]._writing))
        await srv1[0].stop()

    # check the file

    async with MsgReader(path=fn, codec="std-cbor") as rdr:
        msg = await anext(rdr)
        assert isinstance(msg, CBORTag)
        assert getattr(msg, "_cbor_tag", None)
        assert msg.tag == CBOR_TAG_MOAT_FILE_ID
        async for msg in rdr:
            pass
        assert isinstance(msg, CBORTag)
        assert msg.tag == CBOR_TAG_MOAT_FILE_END
        assert "error" not in msg.value, msg.value

    # verify that the next stack reads it back

    async with Scaffold(cfg, use_servers=True, tempdir=tmp_path) as sf:
        await sf.server()
        c2 = await sf.client()
        nn = await fetch(c2, "a")

        assert n.get(P("a")) == nn


@pytest.mark.anyio()
async def test_lsy_switch_server_hard(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        srv1 = await sf.server(init={"Hello": "there!", "test": 123})
        c1 = await sf.client()
        Node()
        await c1.cmd(P("d.set"), P("test.one"), 123)

        await sf.server()
        await srv1[0].cancel()

        res, meta = await c1.cmd(P("d.get"), P("test.one"))
        assert res == 123


@pytest.mark.anyio()
async def test_lsy_switch_server_hard_break(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        srv1 = await sf.server(init={"Hello": "there!", "test": 123})
        c1 = await sf.client()
        Node()
        await c1.cmd(P("d.set"), P("test.one"), 123)

        await sf.server()
        n = 0
        with pytest.raises(EOFError),ungroup:
            async with c1.cmd(P("i.count")).stream_in() as st:
                async for m in st:
                    n += 1
                    if n == 3:
                        await srv1[0].cancel()
        assert n == 3
        res, meta = await c1.cmd(P("d.get"), P("test.one"))
        assert res == 123


@pytest.mark.anyio()
async def test_lsy_switch_server_soft(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        srv1 = await sf.server(init={"Hello": "there!", "test": 123})
        c1 = await sf.client()
        Node()
        await c1.cmd(P("d.set"), P("test.one"), 123)

        await sf.server()
        await srv1[0].stop()

        res, meta = await c1.cmd(P("d.get"), P("test.one"))
        assert res == 123
