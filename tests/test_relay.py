"""
Test the relay implementation
"""
import pytest
from moat.util import attrdict

from moat.micro.compat import TaskGroup, sleep_ms
from moat.micro.part.fake import PINS
from moat.micro.part.relay import Relay


@pytest.mark.anyio
async def test_rly():
    "relay test"
    cfg = attrdict(
        pin=attrdict(server="moat.micro.part.fake.PIN", pin="X"),
        t_on=50,
        t_off=150,
    )

    r = Relay(cfg)
    p = PINS["X"]

    async with TaskGroup() as tg:
        await tg.spawn(r.run, None, _name="RlyTest")
        await sleep_ms(50)

        await p.set(True)
        await r.set(True)
        assert True is p.value
        await r.set(force=False)
        # this starts a timer 150.
        assert False is p.value
        await r.set(True, force=None)  # X
        assert False is p.value
        await sleep_ms(100)
        assert False is p.value
        # the timer runs out after 150 and the (X) starts a new timer 50.
        await sleep_ms(80)
        assert True is p.value
        await r.set(False)
        # the new timer now has 20 remaining.
        assert True is p.value
        await sleep_ms(40)
        assert False is p.value
        tg.cancel()
