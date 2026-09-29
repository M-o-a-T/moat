"""Rehearse the cutover from ``moat kv job`` to ``moat link job``.

This follows ``docs/moat-link-job/cutover.md`` against a Scaffold
server: import the ported snippets from ``examples/moat-link-job``,
convert a MoaT-KV job dump with ``migrate-from-kv -w``, start a runner
per group and mode, and check that the jobs run and report no errors.
MoaT-KV is never contacted.
"""

from __future__ import annotations

import anyio
import pytest
from pathlib import Path as FSPath

import moat.link.job  # noqa:F401 - register cfg
from moat.util import attrdict, combine_dict, yload
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.job import AllJobRunner, AnyJobRunner, SingleJobRunner

pytestmark = pytest.mark.anyio

EXAMPLES = FSPath(__file__).parents[2] / "examples" / "moat-link-job"

# One job per runner mode, plus a second group; 'target: 0' as in production.
KV_DUMP = """\
- !P any.default.copy.a:
    code: !P transform.copy.value
    data: {src: !P home.a, dst: !P home.b}
    target: 0
    repeat: 0
    delay: 10
- !P any.dev.copy.c:
    code: !P transform.copy.value
    data: {src: !P home.c, dst: !P home.d}
    target: 0
- !P at.hostx.default.copy.e:
    code: !P transform.copy.bool
    data: {src: !P home.e, dst: !P home.f}
    target: 0
- !P all.default.sum:
    code: !P transform.multi.sum
    data:
      src: {x: !P home.x, y: !P home.y}
      dst: !P home.xy
      delay: 0
    target: 0
"""


async def _wait_value(c, path, value, timeout=10):
    with anyio.fail_after(timeout):
        while True:
            try:
                if await c.d_get(path) == value:
                    return
            except KeyError:
                pass
            await anyio.sleep(0.1)


async def _wait_started(c, path, timeout=10):
    with anyio.fail_after(timeout):
        while True:
            try:
                st = await c.d_get(path)
            except KeyError:
                pass
            else:
                if st.get("started", 0) > st.get("stopped", 0):
                    await anyio.sleep(0.5)  # let the snippet set up its watcher
                    return
            await anyio.sleep(0.1)


async def test_cutover(cfg, tmp_path):
    "Import, migrate, run every group and mode; no job errors."
    dump = tmp_path / "jobs.yaml"
    dump.write_text(KV_DUMP)
    snippets = " ".join(
        str(EXAMPLES / f"{n}.yaml")
        for n in (
            "transform.copy.value",
            "transform.copy.bool",
            "transform.multi.sum",
        )
    )

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        for p, v in (("a", 1), ("c", 2), ("e", 1), ("x", 3), ("y", 4)):
            await c.d_set(P("home") | p, v)
        for p in ("b", "d", "f", "xy"):
            await c.d_set(P("home") | p, None)
        await c.i_sync()

        # Step: load the ported snippets.
        await sf.run(f"link code : import {snippets}")

        # Step: dry run. Nothing is missing, nothing is stored.
        r = await sf.run(f"link job migrate-from-kv -i {dump}")
        rep = yload(r.stdout)
        assert rep["jobs"] == 4
        assert not rep.get("missing_code"), rep
        assert not rep.get("missing_data"), rep
        assert "stored" not in rep

        # Step: write the job records.
        r = await sf.run(f"link job migrate-from-kv -i {dump} -w")
        assert len(yload(r.stdout)["stored"]) == 4
        await c.i_sync()

        # Step: start one runner per group and mode, as the systemd units do.
        job_cfg = combine_dict(
            attrdict(actor=attrdict(cycle=1, gap=0.2)), sf.cfg["job"], cls=attrdict
        )
        sub = job_cfg["sub"]
        runners = [
            AnyJobRunner(c, job_cfg, sub["group"] + P("default"), nodes=1),
            AnyJobRunner(c, job_cfg, sub["group"] + P("dev"), nodes=1),
            SingleJobRunner(c, job_cfg, sub["single"] + P("hostx.default"), nodes=1),
            AllJobRunner(c, job_cfg, sub["all"] + P("default"), nodes=1),
        ]
        async with anyio.create_task_group() as tg:
            for rn in runners:
                await tg.start(_run, rn)

            # Step: watch. Every job copies its current value …
            await _wait_value(c, P("home.b"), 1)
            await _wait_value(c, P("home.d"), 2)
            # (transform.copy.bool ignores the initial value.)
            await _wait_started(c, job_cfg["state"] + sub["single"] + P("hostx.default.copy.e"))
            await _wait_value(c, P("home.xy"), 7)

            # … and follows changes.
            await c.d_set(P("home.a"), 11)
            await c.d_set(P("home.e"), 0)
            await c.d_set(P("home.y"), 10)
            await _wait_value(c, P("home.b"), 11)
            await _wait_value(c, P("home.f"), False)
            await _wait_value(c, P("home.xy"), 13)

            # The jobs are running, and 'moat link job … list -t' says so.
            r = await sf.run("link job at : list -t")
            assert r.stdout.split() == ["copy.a", "transform.copy.value", c.name]
            r = await sf.run("link job -g dev at : list -t")
            assert r.stdout.split()[1:] == ["transform.copy.value", c.name]

            # No errors below error.job.
            errs = []
            async with c.d.walk(P("error") + job_cfg["prefix"]).stream_in() as mon:
                async for _, p, d, *_ in mon:
                    if isinstance(d, dict) and not d.get("ok", False):
                        errs.append((p, d))
            assert not errs, errs

            tg.cancel_scope.cancel()


async def _run(runner, *, task_status):
    async with runner.run():
        task_status.started()
        await anyio.sleep_forever()
