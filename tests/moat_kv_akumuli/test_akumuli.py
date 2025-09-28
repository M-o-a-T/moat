from __future__ import annotations  # noqa: D100
import anyio
from time import time

from moat.util import P, load_ext
from moat.kv.mock.mqtt import stdtest

from asyncakumuli.mock import AkumuliTester

import subprocess

task = akumuli_task = load_ext("moat.kv.akumuli.task", "task", err=True)

akumuli_model = load_ext("moat.kv.akumuli.model", err=True)
AkumuliRoot = akumuli_model.AkumuliRoot

try:
    res = subprocess.run(["akumulid", "--help"], check=False)
except Exception:
    import pytest

    pytestmark = pytest.mark.skip


def _hook(e):
    e.ns_time = int(time() * 1000000000)


akumuli_model._test_hook = _hook


async def test_basic(free_tcp_port_factory):  # no autojump  # noqa: D103
    async with (
        stdtest(test_0={"init": 125}, n=1, tocks=200) as st,
        st.client(0) as client,
        AkumuliTester(free_tcp_port_factory(), free_tcp_port_factory()).run() as t,
    ):
        await st.run(f"akumuli test add -h 127.0.0.1 -p {t.TCP_PORT}")
        await client.set(P("test.one.two"), value=41)
        await st.run("akumuli test at test.foo.bar add test.one.two whatever foo=bar")
        aki = await AkumuliRoot.as_handler(client)
        aki._cfg.server_default.port = t.TCP_PORT
        st.tg.start_soon(task, client, aki._cfg, aki["test"])
        await anyio.sleep(1)
        await aki["test"].flush()
        await client.set(P("test.one.two"), value=42)
        await anyio.sleep(0.3)
        await aki["test"].flush()
        await anyio.sleep(0.8)
        await client.set(P("test.one.two"), value=43)
        await anyio.sleep(0.3)
        await aki["test"].flush()

        n = 0
        async for x in t.get_data("whatever", tags={}, t_start=time() - 1000, t_end=time() + 1000):
            n += 1
            assert x.value in (41, 42, 43)
            assert abs(time() - x.time) < 10
        assert n > 1
        pass
