"""Tests for ``moat link job migrate-from-kv``.

These only use a fixture file and a Scaffold server; MoaT-KV is never
contacted.
"""

from __future__ import annotations

import pytest

import moat.link.job  # noqa:F401 - register cfg
from moat.util import yload
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.job.migrate import convert, kv_items

pytestmark = pytest.mark.anyio

# What 'moat kv data :.moat.kv.run get -r' prints, roughly.
KV_DUMP = """\
- !P any.default.lamp.off:
    code: !P timer.auto_off
    data:
      src: !P home.lamp.state
      dst: !P home.lamp.cmd
      delay: 600
    delay: 10
    repeat: 0
    target: 0
    ok_after: 5
    backoff: 1.5
    info: switch the lamp off
- !P any.default.copy.temp:
    code: !P transform.copy.value
    data:
      src: !P sensor.temp
      dst: [!P out.temp, !P :.moat.kv.status.temp]
    target: 0
    whatever: 42
- !P at.pi1.dev.blink:
    code: !P test.blink
    data: {}
- !P all.default.keepalive:
    code: !P keepalive.monitor
- !P any.default:
    info: a group without a job
- !P any.default.broken:
    info: no code here
"""


def _items():
    return kv_items(yload(KV_DUMP))


def test_kv_items_forms():
    """The list and the nested-dict 'get -r' forms give the same items."""
    tree = {
        "any": {"default": {"a": {"_": {"code": P("x")}}}},
        "at": {"n": {"g": {"b": {"_": {"code": P("y")}}}}},
    }
    assert kv_items(tree) == [
        (P("any.default.a"), {"code": P("x")}),
        (P("at.n.g.b"), {"code": P("y")}),
    ]
    assert kv_items([{"any.default.a": {"code": "x"}}]) == [
        (P("any.default.a"), {"code": "x"}),
    ]
    with pytest.raises(ValueError, match="get -r"):
        kv_items([{"a": 1, "b": 2}])


def test_convert():
    """Field mapping, dropped fields, skipped entries, group counts."""
    rep = convert(_items())
    jobs = {j.path: j for j in rep.jobs}
    assert set(jobs) == {
        P("any.default.lamp.off"),
        P("any.default.copy.temp"),
        P("at.pi1.dev.blink"),
        P("all.default.keepalive"),
    }
    lamp = jobs[P("any.default.lamp.off")].record
    assert lamp == {
        "code": P("timer.auto_off"),
        "data": {"src": P("home.lamp.state"), "dst": P("home.lamp.cmd"), "delay": 600},
        "delay": 10,
        "repeat": 0,
        "target": 0,
        "ok_after": 5,
        "backoff": 1.5,
        "info": "switch the lamp off",
    }
    copy = jobs[P("any.default.copy.temp")]
    assert "whatever" not in copy.record
    assert copy.notes == ["dropped field 'whatever': 42"]
    assert jobs[P("all.default.keepalive")].record == {
        "code": P("keepalive.monitor"),
        "data": {},
    }
    assert [s["path"] for s in rep.skipped] == [P("any.default"), P("any.default.broken")]

    d = rep.dump()
    assert d["jobs"] == 4
    assert d["groups"] == {"all.default": 1, "any.default": 2, "at.pi1.dev": 1}


async def test_migrate_cli(cfg, tmp_path):
    """Dry run, write, re-run, conflict, force."""
    dump = tmp_path / "jobs.yaml"
    dump.write_text(KV_DUMP)
    prefix = cfg.link.job.prefix

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(P("code.timer.auto_off"), {"code": "return 1"})
        await c.d_set(P("code.transform.copy.value"), {"code": "return 1"})
        await c.d_set(P("home.lamp.state"), True)
        await c.d_set(P("home.lamp.cmd"), False)
        await c.d_set(P("out.temp"), 20)
        await c.i_sync()

        # Dry run: report only.
        r = await sf.run(f"link job migrate-from-kv -i {dump}")
        rep = yload(r.stdout)
        assert rep["jobs"] == 4
        assert set(rep["missing_code"]) == {P("test.blink"), P("keepalive.monitor")}
        assert rep["missing_data"] == {P("sensor.temp"): [P("any.default.copy.temp")]}
        assert rep["kv_internal"] == {P(":.moat.kv.status.temp"): [P("any.default.copy.temp")]}
        assert "stored" not in rep
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + P("any.default.lamp.off"))

        # Write.
        r = await sf.run(f"link job migrate-from-kv -i {dump} -w")
        rep = yload(r.stdout)
        assert len(rep["stored"]) == 4
        await c.i_sync()
        lamp = await c.d_get(prefix + P("any.default.lamp.off"))
        assert lamp["code"] == P("timer.auto_off")
        assert lamp["info"] == "switch the lamp off"
        assert (await c.d_get(prefix + P("at.pi1.dev.blink")))["code"] == P("test.blink")

        # Again: nothing changes.
        r = await sf.run(f"link job migrate-from-kv -i {dump} -w")
        rep = yload(r.stdout)
        assert "stored" not in rep
        assert len(rep["unchanged"]) == 4

        # A changed Link record is not overwritten without --force.
        await c.d_set(prefix + P("any.default.lamp.off"), {"code": P("other"), "data": {}})
        await c.i_sync()
        r = await sf.run(f"link job migrate-from-kv -i {dump} -w")
        rep = yload(r.stdout)
        assert rep["conflicts"] == [P("any.default.lamp.off")]
        await c.i_sync()
        assert (await c.d_get(prefix + P("any.default.lamp.off")))["code"] == P("other")

        r = await sf.run(f"link job migrate-from-kv -i {dump} -w -f")
        rep = yload(r.stdout)
        assert rep["stored"] == [P("any.default.lamp.off")]
        await c.i_sync()
        assert (await c.d_get(prefix + P("any.default.lamp.off")))["code"] == P("timer.auto_off")
