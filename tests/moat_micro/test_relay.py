"""
Test the relay implementation
"""

from __future__ import annotations

import pytest

from moat.lib.micro import sleep_ms
from moat.lib.path import P
from moat.micro._test import mpy_stack

CFG = """
app: dir
r:
  app: part.Relay
  pin: !P p
  t:
    on: 50
    off: 150
p:
  app: _fake.Pin
  pin: X
"""


@pytest.mark.anyio
async def test_rly(tmp_path):
    "fake relay test"
    async with mpy_stack(tmp_path, CFG) as d:
        r = d.sub_at(P("r"))
        p = d.sub_at(P("p"))

        # this starts the min-on timer 50.
        await p(True)
        await r.w(v=True)
        assert True is await p()

        await r.w(f=False)
        # this kills the previous timer and starts a min-off-timer 150.

        assert False is await p()
        await r.w(v=True, f=None)  # X
        assert False is await p()
        await sleep_ms(100)
        assert False is await p()
        # the off timer runs out after 150, i.e. sometime during the next
        # sleep, and the (X) turns the relay on and starts a new
        # min-on-timer 50.
        await sleep_ms(80)
        assert True is await p()
        await r.w(False)
        # the min-on timer has ~20 msec remaining at this point, thus the
        # pin is still on.
        assert True is await p()
        await sleep_ms(40)
        # Now it is not.
        assert False is await p()
