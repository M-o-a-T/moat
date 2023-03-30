"""
Test the relay implementation
"""
import time
from moat.micro.compat import every_ms, sleep_ms, TaskGroup
from moat.micro.part.relay import Relay
from .fake import PINS
from moat.util import attrdict

import pytest

@pytest.mark.anyio
async def test_rly():
    cfg = attrdict(
            pin=attrdict(
                server="tests.fake.PIN",
                pin="X"
            ),
            t_on=50,
            t_off=150,
        )

    r=Relay(cfg)
    p=PINS["X"]

    async with TaskGroup() as tg:
        await tg.spawn(r.run,None)
        await sleep_ms(50)

        await p.set(True)
        await r.set(True)
        assert True == p.value
        await r.set(force=False)
        # this starts a timer 150.
        assert False == p.value
        await r.set(True,force=None)  # X
        assert False == p.value
        await sleep_ms(100)
        assert False == p.value
        # the timer runs out after 150 and the (X) starts a new timer 50.
        await sleep_ms(80)
        assert True == p.value
        await r.set(False)
        # the new timer now has 20 remaining.
        assert True == p.value
        await sleep_ms(40)
        assert False == p.value
        tg.cancel()

