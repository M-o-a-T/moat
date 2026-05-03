#!/usr/bin/python3
from __future__ import annotations

import anyio

from moat.lib.config import CFG
from moat.lib.path import P
from moat.link.client import Link

CFG()

async def run():
    off = True
    lim = 18
    async with Link(CFG.moat.link) as li:
        pid = (await li.get_service(P("s.ug.heizung"))).sub_at(P("z1.r.pid"))
        r=P("home.ass.dyn.sensor.test_z1")
        while True:
            s = await pid.s()
            # print(s)
            await li.d_set(r/"pid_P"/"state",s["split"][0])
            await li.d_set(r/"pid_I"/"state",s["split"][1])
            await li.d_set(r/"pid_D"/"state",s["split"][2])
            await li.d_set(r/"pid_sum"/"state",s["o"])
            await li.d_set(r/"pid_setpoint"/"state",s["state"]["setpoint"])
            await anyio.sleep(30)

anyio.run(run)
