from __future__ import annotations  # noqa: D100

import anyio
import logging
import pytest

from moat.util import ungroup
from moat.lib.codec.cbor import Tag as CBORTag
from moat.lib.codec.moat_cbor import CBOR_TAG_MOAT_FILE_END, CBOR_TAG_MOAT_FILE_ID
from moat.lib.path import P, PathLongener
from moat.lib.rpc import StreamError
from moat.link._test import Scaffold
from moat.link.client import BasicLink
from moat.link.exceptions import ServerLinkLost
from moat.link.meta import MsgMeta
from moat.link.node import Node
from moat.util.msg import MsgReader

logger = logging.getLogger(__name__)


async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    async with bk.monitor(P("#"), qos=0) as mon:
        task_status.started()
        async for msg in mon:
            print(msg)


async def data(s):  # noqa: D103
    await s("a.b.e", 10)
    await s("a.b.f", 11)
    await s("a.b.g.h", 12)
    await s("a.b.g.o", 121)
    await s("a.b.i", 13)
    await s("a.b.j", 14)
    await s("a.c", 15)
    await s("a.c.d", 16)
    await s("a.b.d", 17)


async def fetch(c, p):  # noqa: D103
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
            nn.set(p, d, MsgMeta.restore(m))
        return nn


@pytest.mark.anyio
async def test_lsy_from_server(cfg):  # noqa: D103
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

        if c1._link._last_link is None:  # noqa: SLF001
            await c1._link._last_link_seen.wait()  # noqa: SLF001

        async with BasicLink(cfg, "_test", c1._link._last_link.data) as c2:  # noqa: SLF001
            nn = await fetch(c2, "a")

            assert n.get(P("a")) == nn


@pytest.mark.anyio
async def test_lsy_from_file(cfg, tmp_path):  # noqa: D103
    async with Scaffold(cfg, use_servers=True, tempdir=tmp_path) as sf:
        (sf.tempdir / "data").mkdir()

        srv1 = await sf.server(init={"Hello": "there!", "test": 123})
        n = Node()
        async with sf.client_() as c1:

            async def s(p, v):
                p = P(p)
                await c1.cmd(P("d.set"), p, v)
                n.set(p, v, MsgMeta(origin="Test"))

            await data(s)
        fn = next(iter(srv1._writing))  # noqa: SLF001
        await srv1.stop()

    # check the file

    async with MsgReader(path=fn, codec="std-cbor") as rdr:
        msg = await anext(rdr)
        assert isinstance(msg, CBORTag)
        assert getattr(msg, "_cbor_tag", None)
        assert msg.tag == CBOR_TAG_MOAT_FILE_ID
        async for msg in rdr:  # noqa:B007
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


async def _until_lost(sf, body) -> None:
    """
    Run ``body(client)`` in a client that must end with `ServerLinkLost`
    (clients don't fail over to another server, moat-1uo).
    """
    lost = []
    with anyio.fail_after(5):
        try:
            async with sf.client_() as c:
                await body(c)
                await anyio.sleep_forever()
        except* ServerLinkLost as exc:
            lost.extend(exc.exceptions)
    assert lost


@pytest.mark.anyio
async def test_lsy_switch_server_hard(cfg):
    "the data survives when its server dies; its clients end"
    async with Scaffold(cfg, use_servers=True) as sf:
        srv1 = await sf.server(init={"Hello": "there!", "test": 123})

        async def body(c1):
            await c1.cmd(P("d.set"), P("test.one"), 123)
            await sf.server()
            await srv1.cancel()

        await _until_lost(sf, body)

        c2 = await sf.client()
        res, *_meta = await c2.cmd(P("d.get"), P("test.one"))
        assert res == 123


@pytest.mark.anyio
async def test_lsy_switch_server_hard_break(cfg):
    "a server that dies during a stream ends the stream and the client"
    async with Scaffold(cfg, use_servers=True) as sf:
        srv1 = await sf.server(init={"Hello": "there!", "test": 123})
        n = 0

        async def body(c1):
            nonlocal n
            await c1.cmd(P("d.set"), P("test.one"), 123)
            await sf.server()
            with pytest.raises(EOFError), ungroup:  # noqa:PT012
                async with c1.cmd(P("i.count")).stream_in() as st:
                    async for _m in st:
                        n += 1
                        if n == 3:
                            await srv1.cancel()

        await _until_lost(sf, body)
        assert n == 3

        c2 = await sf.client()
        res, *_meta = await c2.d.get(P("test.one"))
        assert res == 123


@pytest.mark.anyio
async def test_lsy_switch_server_soft(cfg):
    "the data survives when its server stops; its clients end"
    async with Scaffold(cfg, use_servers=True) as sf:
        srv1 = await sf.server(init={"Hello": "there!", "test": 123})

        async def body(c1):
            await c1.cmd(P("d.set"), P("test.one"), 123)
            await sf.server()
            await srv1.stop()

        await _until_lost(sf, body)

        c2 = await sf.client()
        res, *_meta = await c2.cmd(P("d.get"), P("test.one"))
        assert res == 123
