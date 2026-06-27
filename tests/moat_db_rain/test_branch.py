"""Round-trip tests for the Phase-3 branch models of ``moat.db.rain``."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import moat.db.util  # noqa: F401  — attaches the sqlite ``foreign_keys=ON`` pragma listener
from moat.db.rain import model as rain
from moat.lib.path import Path


def _seed_graph(sess):
    """Build a small but wide site graph; return the key objects by tag."""
    site = rain.Site(name="home")
    ctrl = rain.Controller(name="C1", location="rack", site=site)
    feed = rain.Feed(name="main", site=site)
    eg = rain.EnvGroup(name="std", site=site)
    valve = rain.Valve(
        name="V1",
        command=Path.from_str("home.v1"),
        state=Path.from_str("home.v1.state"),
        location="port1",
        flow=0.5,
        area=10.0,
        feed=feed,
        controller=ctrl,
        envgroup=eg,
    )
    day = rain.Day(name="daily")
    dt = rain.DayTime(descr="Mon 06:00", day=day)
    dr = rain.DayRange(name="morning")
    dr.days.add(day)
    xr = rain.DayRange(name="noon")
    xr.days.add(day)
    group = rain.Group(name="G1", site=site)
    group.valves.add(valve)
    group.days.add(dr)
    group.xdays.add(xr)
    go = rain.GroupOverride(
        group=group, start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=3600, allowed=True
    )
    vo = rain.ValveOverride(
        valve=valve, start=datetime(2026, 1, 1, 7, tzinfo=UTC), duration=1800, running=True
    )
    ga = rain.GroupAdjust(group=group, start=datetime(2026, 1, 1, tzinfo=UTC), factor=1.2)
    sched = rain.Schedule(valve=valve, start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=900)
    lvl = rain.Level(valve=valve, time=datetime(2026, 1, 1, 5, tzinfo=UTC), level=5.0)
    hist = rain.History(site=site, time=datetime(2026, 1, 1, 5, tzinfo=UTC), rain=0.2, temp=18.0)
    log = rain.Log(site=site, logger="sched", text="started")
    sess.add_all([
        site,
        ctrl,
        feed,
        eg,
        valve,
        day,
        dt,
        dr,
        xr,
        group,
        go,
        vo,
        ga,
        sched,
        lvl,
        hist,
        log,
    ])
    sess.flush()
    return {
        "site": site,
        "ctrl": ctrl,
        "feed": feed,
        "eg": eg,
        "valve": valve,
        "day": day,
        "dt": dt,
        "dr": dr,
        "xr": xr,
        "group": group,
        "go": go,
        "vo": vo,
        "ga": ga,
        "sched": sched,
        "lvl": lvl,
        "hist": hist,
        "log": log,
    }


def test_full_graph_links(engine):
    """Every bidirectional link — scalar, one-to-many, and M2M — resolves."""
    with Session(engine) as sess:
        g = _seed_graph(sess)
        assert g["valve"].groups == {g["group"]}
        assert g["group"].valves == {g["valve"]}
        assert g["group"].days == {g["dr"]}
        assert g["group"].xdays == {g["xr"]}
        assert g["dr"].groups == {g["group"]}
        assert g["xr"].xgroups == {g["group"]}
        assert g["day"].ranges == {g["dr"], g["xr"]}
        assert g["ctrl"].valves == {g["valve"]}
        assert g["feed"].valves == {g["valve"]}
        assert g["eg"].valves == {g["valve"]}
        assert g["site"].controllers == {g["ctrl"]}
        assert g["site"].groups == {g["group"]}
        assert g["site"].histories == {g["hist"]}
        assert g["site"].logs == {g["log"]}
        assert g["valve"].schedules == {g["sched"]}
        assert g["valve"].levels == {g["lvl"]}
        assert g["valve"].overrides == {g["vo"]}
        assert g["group"].overrides == {g["go"]}
        assert g["group"].adjusters == {g["ga"]}
        # timedelta / end properties
        assert g["go"].duration_td == timedelta(seconds=3600)
        assert g["go"].end == datetime(2026, 1, 1, 7, tzinfo=UTC)
        assert g["vo"].end == datetime(2026, 1, 1, 7, 30, tzinfo=UTC)
        assert g["sched"].duration_td == timedelta(seconds=900)
        assert g["valve"].max_run_td is None
        assert g["valve"].min_delay_td is None
        assert g["valve"].command == Path.from_str("home.v1")
        assert g["valve"].state == Path.from_str("home.v1.state")
        # a site-level log (null controller/valve) is in site.logs only
        assert g["ctrl"].logs == set()
        assert g["valve"].logs == set()


def test_valve_unique_per_controller(engine):
    """``(controller, name)`` is unique; the same name on another controller is fine."""
    with Session(engine) as sess:
        site = rain.Site(name="home")
        c1 = rain.Controller(name="C1", location="x", site=site)
        c2 = rain.Controller(name="C2", location="x", site=site)
        feed = rain.Feed(name="main", site=site)
        eg = rain.EnvGroup(name="std", site=site)
        sess.add(
            rain.Valve(
                name="V",
                command=Path.from_str("h.v1"),
                location="p",
                flow=0.5,
                area=1.0,
                feed=feed,
                controller=c1,
                envgroup=eg,
            )
        )
        sess.flush()
        sess.add(
            rain.Valve(
                name="V",
                command=Path.from_str("h.v2"),
                location="p",
                flow=0.5,
                area=1.0,
                feed=feed,
                controller=c2,
                envgroup=eg,
            )
        )
        sess.flush()
        sess.add(
            rain.Valve(
                name="V",
                command=Path.from_str("h.v3"),
                location="p",
                flow=0.5,
                area=1.0,
                feed=feed,
                controller=c1,
                envgroup=eg,
            )
        )
        with pytest.raises(IntegrityError):
            sess.flush()
        sess.rollback()


def test_cascade_valve_removes_links_and_children(engine):
    """Deleting a valve cascades to its schedules/levels/overrides and drops M2M links."""
    with Session(engine) as sess:
        g = _seed_graph(sess)
        vid, gid = g["valve"].id, g["group"].id
        sid, lid, void = g["sched"].id, g["lvl"].id, g["vo"].id
        sess.commit()

    with Session(engine) as sess:
        assert sess.scalar(select(func.count()).select_from(rain.group_valves)) == 1

    with Session(engine) as sess:
        sess.delete(sess.get(rain.Valve, vid))
        sess.commit()

    with Session(engine) as sess:
        assert sess.get(rain.Schedule, sid) is None
        assert sess.get(rain.Level, lid) is None
        assert sess.get(rain.ValveOverride, void) is None
        assert sess.scalar(select(func.count()).select_from(rain.group_valves)) == 0
        gr = sess.get(rain.Group, gid)
        assert gr is not None
        assert gr.valves == set()


def test_cascade_group_removes_overrides_adjusters(engine):
    """Deleting a group cascades to its overrides/adjusters and drops its M2M links."""
    with Session(engine) as sess:
        g = _seed_graph(sess)
        gid, goid, gaid = g["group"].id, g["go"].id, g["ga"].id
        sess.commit()

    with Session(engine) as sess:
        sess.delete(sess.get(rain.Group, gid))
        sess.commit()

    with Session(engine) as sess:
        assert sess.get(rain.GroupOverride, goid) is None
        assert sess.get(rain.GroupAdjust, gaid) is None
        assert sess.scalar(select(func.count()).select_from(rain.group_days)) == 0
        assert sess.scalar(select(func.count()).select_from(rain.group_xdays)) == 0
        assert sess.scalar(select(func.count()).select_from(rain.group_valves)) == 0


def test_cascade_site_removes_descendants(engine):
    """Deleting a site cascades through controllers/valves down to schedules and logs."""
    with Session(engine) as sess:
        g = _seed_graph(sess)
        ids = {
            rain.Site: g["site"].id,
            rain.Controller: g["ctrl"].id,
            rain.Valve: g["valve"].id,
            rain.Feed: g["feed"].id,
            rain.EnvGroup: g["eg"].id,
            rain.Group: g["group"].id,
            rain.GroupOverride: g["go"].id,
            rain.ValveOverride: g["vo"].id,
            rain.GroupAdjust: g["ga"].id,
            rain.Schedule: g["sched"].id,
            rain.Level: g["lvl"].id,
            rain.History: g["hist"].id,
            rain.Log: g["log"].id,
        }
        sess.commit()

    with Session(engine) as sess:
        sess.delete(sess.get(rain.Site, ids[rain.Site]))
        sess.commit()

    with Session(engine) as sess:
        for cls, oid in ids.items():
            assert sess.get(cls, oid) is None, f"{cls.__name__} #{oid} survived site delete"


def test_valve_link_paths_optional(engine):
    """A valve may be monitor-only (state, no command) or control-only (command, no state)."""
    with Session(engine) as sess:
        site = rain.Site(name="home")
        ctrl = rain.Controller(name="C1", location="rack", site=site)
        feed = rain.Feed(name="main", site=site)
        eg = rain.EnvGroup(name="std", site=site)
        v_mon = rain.Valve(
            name="Vmon",
            state=Path.from_str("home.v1.state"),
            location="p",
            flow=0.5,
            area=1.0,
            feed=feed,
            controller=ctrl,
            envgroup=eg,
        )
        v_ctl = rain.Valve(
            name="Vctl",
            command=Path.from_str("home.v2"),
            location="p",
            flow=0.5,
            area=1.0,
            feed=feed,
            controller=ctrl,
            envgroup=eg,
        )
        sess.add_all([v_mon, v_ctl])
        sess.flush()
        assert v_mon.command is None
        assert v_mon.state == Path.from_str("home.v1.state")
        assert v_ctl.command == Path.from_str("home.v2")
        assert v_ctl.state is None
