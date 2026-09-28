"""
Tests for the ``heat.ha.override`` job snippet (examples/moat-dev-heat):
an override item as a Home Assistant value entity plus a "manual" switch.
Runs the snippet in the MoaT-Link job runner.
"""

from __future__ import annotations

import anyio
import pytest
import time
from pathlib import Path as FSPath

import moat.link.job  # noqa: F401  # registers the job runner's config
from moat.util import attrdict, combine_dict, yload
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.code import CODE_EXEC_ROOT
from moat.link.job import AnyJobRunner

from typing import Any

CODE = FSPath(__file__).parents[2] / "examples" / "moat-dev-heat" / "code.heat.ha.override.yaml"
SNIPPET = P("heat.ha.override")

DST = P("test.app.heat.override.wp")
VAL = P("test.home.ass.dyn.switch.heizung.wp")
MAN = P("test.home.ass.dyn.switch.heizung.wp_override")
ACT = P("test.app.heat.pump.out")

pytestmark = pytest.mark.anyio


class Env:
    "a job runner with the snippet, and a client to play Home Assistant"

    def __init__(self, sf: Scaffold, c: Any, obs: Any) -> None:
        self.sf = sf
        self.c = c  # the job runner's client, also used for writing
        self.obs = obs  # a separate client for watching
        self.seen: dict[Any, list[Any]] = {}

    async def _watch(self, path, *, task_status) -> None:
        async with self.obs.d_watch(path, state=None, mark=True) as mon:
            async for v in mon:
                if v is None:
                    task_status.started()
                    continue
                self.seen.setdefault(path, []).append(v)

    async def start(self, tg, **data: Any) -> None:
        "store the snippet and the job, start the runner and watchers"
        c = self.c
        await c.d_set(CODE_EXEC_ROOT + SNIPPET, yload(CODE.read_text()))
        cfg = combine_dict(
            attrdict(actor=attrdict(cycle=1, gap=0.2)), self.sf.cfg["job"], cls=attrdict
        )
        sub = cfg["sub"]["group"] + P("default")
        job = dict(
            code=SNIPPET,
            target=time.time(),
            data=dict(dst=DST, value=VAL, manual=MAN, actual=ACT, key="run", **data),
        )
        await c.d_set(cfg["prefix"] + sub + P("wp"), job)
        for p in (DST, VAL / "state", MAN / "state"):
            await tg.start(self._watch, p)
        await c.i_sync()
        runner = AnyJobRunner(c, cfg, sub, nodes=1)
        await tg.start(self._run, runner)
        self.state = cfg["state"] + sub + P("wp")

    @staticmethod
    async def _run(runner, *, task_status) -> None:
        async with runner.run():
            task_status.started()
            await anyio.sleep_forever()

    async def last(self, path, pred, timeout: float = 10) -> Any:
        "wait until the last value seen at ``path`` satisfies ``pred``"
        with anyio.fail_after(timeout):
            while True:
                v = self.seen.get(path)
                if v and pred(v[-1]):
                    return v[-1]
                await anyio.sleep(0.05)

    async def set(self, path, value=Any) -> None:
        "HA (or someone) writes"
        if value is Any:
            await self.c.d_set(path)
        else:
            await self.c.d_set(path, value)


async def test_override(cfg) -> None:
    "manual on/off, value changes, the actual state shadowed, external changes"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
        sf.client_() as obs,
        anyio.create_task_group() as tg,
    ):
        e = Env(sf, c, obs)
        await c.d_set(ACT, {"run": True})
        await e.start(tg)

        # automatic: the value entity shows the actual state
        await e.last(MAN / "state", lambda v: v is False)
        await e.last(VAL / "state", lambda v: v is True)
        await e.set(ACT, {"run": False})
        await e.last(VAL / "state", lambda v: v is False)

        # flipping the value while automatic has no lasting effect
        await e.set(VAL / "cmd", True)
        await anyio.sleep(0.3)
        assert DST not in e.seen
        assert e.seen[VAL / "state"][-1] is False

        # manual on: the override takes the last command
        await e.set(MAN / "cmd", True)
        assert await e.last(DST, lambda v: v is not None) is True
        await e.last(MAN / "state", lambda v: v is True)
        await e.last(VAL / "state", lambda v: v is True)

        # a command while manual changes the override
        await e.set(VAL / "cmd", False)
        await e.last(DST, lambda v: v is False)
        await e.last(VAL / "state", lambda v: v is False)

        # someone else clears the override: HA follows
        await e.set(DST)
        await e.last(MAN / "state", lambda v: v is False)
        await e.set(ACT, {"run": True})
        await e.last(VAL / "state", lambda v: v is True)

        # ... or sets it, in the wrapped form
        await e.set(DST, {"value": False, "reason": "service"})
        await e.last(MAN / "state", lambda v: v is True)
        await e.last(VAL / "state", lambda v: v is False)

        # manual off: automatic again
        await e.set(MAN / "cmd", False)
        await e.last(MAN / "state", lambda v: v is False)
        await e.last(VAL / "state", lambda v: v is True)
        with pytest.raises(KeyError):
            await c.d_get(DST)
        tg.cancel_scope.cancel()


async def test_manual_without_command(cfg) -> None:
    "manual on before any value command: keep what the heating does now"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
        sf.client_() as obs,
        anyio.create_task_group() as tg,
    ):
        e = Env(sf, c, obs)
        await c.d_set(ACT, {"run": True})
        await e.start(tg)
        await e.last(MAN / "state", lambda v: v is False)
        await e.set(MAN / "cmd", True)
        assert await e.last(DST, lambda v: v is not None) is True
        tg.cancel_scope.cancel()
