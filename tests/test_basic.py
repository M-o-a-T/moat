import anyio
from time import time

from distkv.util import P, load_ext
from distkv.mock.mqtt import stdtest

from asyncakumuli.mock import Tester, TCP_PORT

akumuli_task = load_ext("distkv_ext.akumuli", "task")
task = akumuli_task.task

akumuli_model = load_ext("distkv_ext.akumuli", "model")
AkumuliRoot = akumuli_model.AkumuliRoot


def _hook(e):
    e.ns_time = int(time() * 1000000000)


akumuli_model._test_hook = _hook


async def test_basic():  # no autojump
    async with stdtest(test_0={"init": 125}, n=1, tocks=200) as st, st.client(
        0
    ) as client, Tester().run() as t:
        await st.run(f"akumuli server test -h 127.0.0.1 -p {TCP_PORT}")
        await st.run("akumuli set test.foo.bar test.one.two whatever foo=bar")
        aki = await AkumuliRoot.as_handler(client)
        await st.tg.spawn(task, client, client._cfg.akumuli, aki["test"])
        await anyio.sleep(0.5)
        await client.set(P("test.one.two"), value=42)
        await anyio.sleep(0.5)
        await aki["test"].flush()

        n = 0
        async for x in t.get_data("whatever", tags={}, t_start=time() - 1000, t_end=time() + 1000):
            n += 1
            assert x[0] == 42
            assert abs(time() - x[1].timestamp()) < 10
        assert n == 1
        pass
