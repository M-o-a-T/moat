from __future__ import annotations  # noqa: D100

import anyio
import pytest

from moat.util import P
from moat.link._test import Scaffold
from moat.link.client import Link


async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    async with bk.monitor(P("#"), qos=0) as mon:
        task_status.started()
        async for msg in mon:
            print(msg)


class Supi(Link):  # noqa: D101
    async def cmd_supi(self):  # noqa: D102
        return "Yes"

    async def stream_supa(self, msg):  # noqa: D102
        async with msg.stream_out() as s:
            for i in range(msg.get(0, 3)):
                await s.send(i + 1)


@pytest.mark.anyio
async def test_c2c_basic(cfg):  # noqa: D103
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.tg.start(_dump, sf)
        _s1 = await sf.server(name="sx1", init={"Hello": "there!", "test": 123})
        _s2 = await sf.server(name="sx2")
        c = await sf.client()
        async with c.monitor(P(":R.run.service.main.+"), retained=False) as mcl:
            async for m in mcl:
                if m.topic[-1] != "conn":
                    continue
                if m.meta.origin == c.link.server_name:
                    continue
                break
        c2 = await sf.client(cli=Supi(cfg.link, "sup"))

        c.add_sub("srv")
        c2.add_sub("srv")
        c2.add_sub("cl")
        assert c.link.server_name != c2.link.server_name

        await anyio.sleep(0.2)

        cln = set()
        async with c2.cl().stream_in() as mm:
            async for m in mm:
                cln.add(m[0])
        assert len(cln) == 2
        assert "sup" in cln

        # cross server
        sup = getattr(c.srv, c2.link.server_name).cl.sup
        res = await sup.supi()
        assert res[0] == "Yes"
        # XXX 'res' should not be a message

        nn = []
        async with sup.supa().stream_in() as mm:
            async for m in mm:
                nn.append(m[0])
        assert nn == [1, 2, 3]

        # same server, don't do this
        sup = c2.cl.sup
        res = await sup.supi()
        assert res[0] == "Yes"
        # XXX 'res' should not be a message

        nn = []
        async with sup.supa(2).stream_in() as mm:
            async for m in mm:
                nn.append(m[0])
        assert nn == [1, 2]

        # same server
        sup = getattr(c2.srv, c2.link.server_name).cl.sup
        res = await sup.supi()
        assert res[0] == "Yes"
        # XXX 'res' should not be a message

        nn = []
        async with sup.supa(4).stream_in() as mm:
            async for m in mm:
                nn.append(m[0])
        assert nn == [1, 2, 3, 4]
