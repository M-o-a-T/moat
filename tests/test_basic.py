import anyio
from functools import partial

from moat.util import P, load_ext, attrdict
from moat.kv.mock.mqtt import stdtest

knx_mock = load_ext("moat.kv.knx.mock")
Tester = knx_mock.Tester
task = load_ext("moat.kv.knx.task", "task")
KNXroot = load_ext("moat.kv.knx.model", "KNXroot")


async def test_basic():
    async with (
            stdtest(test_0={"init": 125}, n=1, tocks=200) as st,
            st.client(0) as client,
            Tester().run() as t,
        ):
        await st.run(f"knx server test localhost -h 127.0.0.1 -p {knx_mock.TCP_PORT}")
        await st.run("knx addr -t in -m power test 1/2/3 -a dest test.some.power")
        await st.run("knx addr -t in -m binary test 1/2/4 -a dest test.some.switch")
        await st.run("knx addr -t in -m percentU8 test 1/2/5 -a dest test.some.percent")
        await st.run("knx addr -t out -m power test 2/3/4 -a src test.some.other.power")
        await st.run("knx addr -t out -m binary test 2/3/5 -a src test.some.other.switch")
        await st.run("knx addr -t out -m percentU8 test 2/3/6 -a src test.some.other.percent")
        knx = await KNXroot.as_handler(client)

        await st.run("data : get -rd_", do_stdout=False)

        evt = anyio.Event()
        st.tg.start_soon(
            partial(task, client, attrdict(server_default=attrdict(port=3671)), knx["test"]["localhost"], evt=evt)
        )
        await evt.wait()

        se = t.exposed_sensor("some_sensor", "1/2/3", value_type="power")
        sw = t.switch("some_switch", "1/2/4")
        sp = t.exposed_sensor("some_percent", "1/2/5", value_type="percentU8")
        te = t.sensor("some_other_sensor", "2/3/4", value_type="power")
        tw = t.binary_sensor("some_other_switch", "2/3/5")
        tp = t.sensor("some_other_percent", "2/3/6", value_type="percentU8")
        assert te.sensor_value.value is None
        assert tw.state.value == 2  # None
        assert tp.sensor_value.value is None
        await anyio.sleep(2.5)

        await se.set(42)
        await sw.set_on()
        await sp.set(18)
        await client.set(P("test.some.other.power"), 33)
        await client.set(P("test.some.other.switch"), True)
        await client.set(P("test.some.other.percent"), 68)

        await anyio.sleep(2.5)
        await st.run("data : get -rd_", do_stdout=False)

        assert te.sensor_value.value == 33
        assert tw.state.value == 1
        assert tp.sensor_value.value == 68

        ve = await client.get(P("test.some.power"))
        vw = await client.get(P("test.some.switch"))
        vp = await client.get(P("test.some.percent"))
        assert ve.value == 42
        assert vw.value == 1
        assert vp.value == 18
