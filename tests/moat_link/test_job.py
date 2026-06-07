"""Smoke tests for ``moat.link.job``.

These verify the end-to-end job runner against a real MQTT broker plus
MoaT-Link server. They cover:

* Job records stored under the configured ``job`` prefix are picked up.
* The configured code snippet is executed.
* Run state ends up under ``run.job`` (configurable).
* Code-reference paths are resolved via ``moat.link.code``.
"""

from __future__ import annotations

import anyio
import pytest
import time

from moat.util import attrdict, combine_dict
from moat.lib.config import CfgStore
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.code import CODE_EXEC_ROOT
from moat.link.job import JOB_ROOT_DEFAULT, STATE_ROOT_DEFAULT, AnyJobRunner

# Ensure the job sub-config is loaded once for the whole module.
CfgStore.with_("moat.link.job")


@pytest.mark.anyio
async def test_default_paths_match_config(cfg):
    "The defaults exposed by the module match the config's job section."
    assert P("job") == JOB_ROOT_DEFAULT
    assert P("run.job") == STATE_ROOT_DEFAULT
    job_cfg = cfg.link["job"]
    assert job_cfg["prefix"] == JOB_ROOT_DEFAULT
    assert job_cfg["state"] == STATE_ROOT_DEFAULT


@pytest.mark.anyio
async def test_job_runs_and_records_state(cfg):
    "End-to-end: define one job, let the runner pick it up, check state."
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "world!"}),
        sf.client_() as c,
    ):
        # A trivial async snippet that returns its single argument.
        await c.d_set(
            CODE_EXEC_ROOT + P("test.greet"),
            dict(code="return 'hi ' + who", vars=dict(who="world"), is_async=True),
        )

        # Tighten the actor cycle so the test doesn't have to wait 20 s.
        job_cfg = combine_dict(
            attrdict(actor=attrdict(cycle=1, gap=0.2)),
            sf.cfg["job"],
            cls=attrdict,
        )
        sub = job_cfg["sub"]["group"] + P("default")
        job_path = job_cfg["prefix"] + sub + P("greet")
        state_path = job_cfg["state"] + sub + P("greet")

        # Define one job that runs immediately.
        await c.d_set(
            job_path,
            dict(
                code=P("test.greet"),
                data=dict(who="there"),
                target=time.time(),
                repeat=0,
                delay=100,
                backoff=1.1,
            ),
        )
        await c.i_sync()

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            with anyio.fail_after(15):
                while True:
                    try:
                        st = await c.d_get(state_path)
                    except KeyError:
                        st = None
                    if isinstance(st, dict) and st.get("result") == "hi there":
                        break
                    await anyio.sleep(0.1)
            tg.cancel_scope.cancel()
