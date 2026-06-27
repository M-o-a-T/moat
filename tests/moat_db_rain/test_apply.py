"""Tests for the rich ``apply()`` methods of ``moat.db.rain`` (Phase 4)."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import moat.db.util  # noqa: F401  — attaches the sqlite ``foreign_keys=ON`` pragma listener
from moat.util import ctx_as
from moat.db.rain import model as rain
from moat.db.schema import Base
from moat.db.util import Mgr, session
from moat.lib.path import Path


@pytest.fixture
def engine(tmp_path):
    """A throwaway sqlite engine with the rain schema materialized."""
    eng = create_engine(f"sqlite:///{tmp_path}/rain.db")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _site(sess, name):
    """Add and flush a bare site; return it."""
    site = rain.Site(name=name)
    sess.add(site)
    sess.flush()
    return site


def _seed_site(sess, name):
    """A site with a feed, controller, and env group of standard names."""
    site = rain.Site(name=name)
    feed = rain.Feed(name="main", site=site)
    ctrl = rain.Controller(name="C1", location="rack", site=site)
    eg = rain.EnvGroup(name="std", site=site)
    sess.add_all([site, feed, ctrl, eg])
    sess.flush()
    return site


def _valve_kwargs(**extra):
    """The required valve apply kwargs (site + parents + scalars)."""
    kw = {
        "site": "home",
        "feed": "main",
        "controller": "C1",
        "envgroup": "std",
        "location": "p",
        "flow": 0.5,
        "area": 1.0,
    }
    kw.update(extra)
    return kw


def test_sensor_apply(engine):
    """apply() wires the site by name, converts state str→Path, locks kind."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _site(sess, "home")
        s = rain.Sensor(name="r1")
        sess.add(s)
        s.apply(site="home", kind="rain", state="home.rain", weight=5)
        sess.flush()
        assert s.site.name == "home"
        assert s.kind == "rain"
        assert s.state == Path.from_str("home.rain")
        assert s.weight == 5

        # kind is immutable once set
        with pytest.raises(ValueError, match="kinds cannot be changed"):
            s.apply(kind="temp")
        # state cannot be cleared
        with pytest.raises(ValueError, match="state path"):
            s.apply(state=None)


def test_envgroup_and_controller_apply(engine):
    """apply() attaches env groups and controllers to a site by name."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _site(sess, "home")
        eg = rain.EnvGroup(name="std")
        sess.add(eg)
        eg.apply(site="home", factor=1.5, rain=False)
        c = rain.Controller(name="C1")
        sess.add(c)
        c.apply(site="home", location="rack", max_on=5)
        sess.flush()
        assert eg.site.name == "home"
        assert eg.factor == 1.5
        assert eg.rain is False
        assert c.site.name == "home"
        assert c.location == "rack"
        assert c.max_on == 5

        # missing site on a new entity is rejected
        with pytest.raises(ValueError, match="site"):
            rain.EnvGroup(name="x").apply()


def test_feed_apply_flow_monitor(engine):
    """apply() sets/clears flow_monitor as a Path via a dotted string."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _site(sess, "home")
        f = rain.Feed(name="main")
        sess.add(f)
        f.apply(site="home", flow_monitor="home.flow")
        sess.flush()
        assert f.flow_monitor == Path.from_str("home.flow")

        f.apply(flow_monitor="-")  # clear
        assert f.flow_monitor is None
        f.apply(flow_monitor="home.flow2")
        assert f.flow_monitor == Path.from_str("home.flow2")
        f.apply(flow_monitor=None)
        assert f.flow_monitor is None


def test_history_apply(engine):
    """apply() attaches a history sample to a site by name."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _site(sess, "home")
        h = rain.History(time=datetime(2026, 1, 1, tzinfo=UTC))
        sess.add(h)
        h.apply(site="home", rain=2.5, temp=12.0)
        sess.flush()
        assert h.site.name == "home"
        assert h.rain == 2.5
        assert h.temp == 12.0


def test_valve_apply_full(engine):
    """apply() resolves feed/controller/envgroup within the site and sets paths."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        v = rain.Valve(name="V1")
        sess.add(v)
        v.apply(**_valve_kwargs(command="home.v1", state="home.v1.state"))
        sess.flush()
        assert v.feed.name == "main"
        assert v.feed.site.name == "home"
        assert v.controller.name == "C1"
        assert v.controller.site.name == "home"
        assert v.envgroup.name == "std"
        assert v.command == Path.from_str("home.v1")
        assert v.state == Path.from_str("home.v1.state")
        assert v.flow == 0.5
        assert v.area == 1.0


def test_valve_apply_scoped_lookup(engine):
    """Identically-named parents in two sites resolve to the site's own."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "a")
        _seed_site(sess, "b")
        v = rain.Valve(name="V1")
        sess.add(v)
        v.apply(**_valve_kwargs(site="b"))
        sess.flush()
        assert v.feed.site.name == "b"
        assert v.controller.site.name == "b"


def test_valve_apply_paths_clear(engine):
    """command/state clear via '-' or None; a valve may be monitor- or control-only."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        v = rain.Valve(name="V1")
        sess.add(v)
        v.apply(**_valve_kwargs(command="home.v1", state="home.v1.state"))
        sess.flush()
        v.apply(command="-")  # monitor-only
        assert v.command is None
        assert v.state == Path.from_str("home.v1.state")
        v.apply(state=None)  # control-only
        assert v.state is None


def test_valve_apply_required_missing(engine):
    """A new valve missing a required FK or the site anchor is rejected."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        v = rain.Valve(name="V1")
        sess.add(v)
        with pytest.raises(ValueError, match="feed"):
            v.apply(site="home", controller="C1", envgroup="std", location="p", flow=0.5, area=1.0)
        v2 = rain.Valve(name="V2")
        sess.add(v2)
        with pytest.raises(ValueError, match="site"):
            v2.apply(location="p", flow=0.5, area=1.0)


def test_valve_apply_derives_site_from_parent(engine):
    """Omitting 'site' on an existing valve derives it from a linked parent."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        v = rain.Valve(name="V1")
        sess.add(v)
        v.apply(**_valve_kwargs())
        sess.flush()
        v.apply(comment="moved", flow=0.6)  # no 'site' restated
        sess.flush()
        assert v.comment == "moved"
        assert v.flow == 0.6


def test_apply_error_paths(engine):
    """Every required-FK / clear-rejected raise in apply() fires."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")

        # site=None is rejected (cannot clear a required site).
        for ctor, kw in [
            (rain.EnvGroup, {"site": None}),
            (rain.Sensor, {"site": None, "kind": "rain", "state": "x"}),
            (rain.Feed, {"site": None}),
            (rain.Controller, {"site": None}),
            (rain.History, {"site": None, "time": datetime(2026, 1, 1, tzinfo=UTC)}),
            (
                rain.Valve,
                {
                    "site": None,
                    "feed": "main",
                    "controller": "C1",
                    "envgroup": "std",
                    "location": "p",
                    "flow": 0.5,
                    "area": 1.0,
                },
            ),
        ]:
            o = ctor()
            sess.add(o)
            with pytest.raises(ValueError, match="site"):
                o.apply(**kw)

        # a brand-new entity with no site at all is rejected.
        for ctor in [rain.EnvGroup, rain.Feed, rain.Controller]:
            o = ctor()
            sess.add(o)
            with pytest.raises(ValueError, match="site"):
                o.apply()
        h = rain.History(time=datetime(2026, 1, 1, tzinfo=UTC))
        sess.add(h)
        with pytest.raises(ValueError, match="site"):
            h.apply()

        # Sensor: kind cannot be None; state cannot be None.
        s = rain.Sensor(name="r")
        sess.add(s)
        with pytest.raises(ValueError, match="kind"):
            s.apply(site="home", kind=None, state="x")
        s2 = rain.Sensor(name="r2")
        sess.add(s2)
        with pytest.raises(ValueError, match="state path"):
            s2.apply(site="home", kind="rain", state=None)

        # Valve: each required parent rejects None and absence-on-new.
        v = rain.Valve(name="V")
        sess.add(v)
        with pytest.raises(ValueError, match="feed"):
            v.apply(
                site="home",
                feed=None,
                controller="C1",
                envgroup="std",
                location="p",
                flow=0.5,
                area=1.0,
            )
        v2 = rain.Valve(name="V2")
        sess.add(v2)
        with pytest.raises(ValueError, match="controller"):
            v2.apply(
                site="home",
                feed="main",
                controller=None,
                envgroup="std",
                location="p",
                flow=0.5,
                area=1.0,
            )
        v3 = rain.Valve(name="V3")
        sess.add(v3)
        with pytest.raises(ValueError, match="controller"):
            v3.apply(site="home", feed="main", envgroup="std", location="p", flow=0.5, area=1.0)
        v4 = rain.Valve(name="V4")
        sess.add(v4)
        with pytest.raises(ValueError, match="env group"):
            v4.apply(
                site="home",
                feed="main",
                controller="C1",
                envgroup=None,
                location="p",
                flow=0.5,
                area=1.0,
            )
        v5 = rain.Valve(name="V5")
        sess.add(v5)
        with pytest.raises(ValueError, match="env group"):
            v5.apply(site="home", feed="main", controller="C1", location="p", flow=0.5, area=1.0)


def test_apply_noop_paths(engine):
    """Omitting optional/unchanged fields is a no-op (covers partial branches)."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _site(sess, "home")
        # Sensor: same-kind no-op; apply without state.
        s = rain.Sensor(name="r")
        sess.add(s)
        s.apply(site="home", kind="rain", state="home.r")
        sess.flush()
        s.apply(kind="rain")  # unchanged → no raise
        s.apply(weight=7)  # no state field → state untouched
        assert s.weight == 7
        assert s.state == Path.from_str("home.r")
        # Feed: apply without flow_monitor leaves it alone.
        f = rain.Feed(name="main")
        sess.add(f)
        f.apply(site="home", flow_monitor="home.flow")
        sess.flush()
        f.apply(comment="x")
        assert f.flow_monitor == Path.from_str("home.flow")
        # EnvGroup: update without re-stating the site.
        eg = rain.EnvGroup(name="std")
        sess.add(eg)
        eg.apply(site="home")
        sess.flush()
        eg.apply(factor=2.0)
        assert eg.factor == 2.0
        # Controller / History: update without re-stating the site.
        c = rain.Controller(name="C1")
        sess.add(c)
        c.apply(site="home", location="rack")
        sess.flush()
        c.apply(max_on=4)
        assert c.max_on == 4
        h = rain.History(time=datetime(2026, 1, 1, tzinfo=UTC))
        sess.add(h)
        h.apply(site="home")
        sess.flush()
        h.apply(rain=1.0)
        assert h.rain == 1.0


def test_schedule_end(engine):
    """Schedule.end is start + duration_td."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        v = rain.Valve(name="V1")
        sess.add(v)
        v.apply(**_valve_kwargs())
        sess.flush()
        sch = rain.Schedule(
            start=datetime(2026, 1, 1, 6, tzinfo=UTC),
            duration=900,
            valve=v,
        )
        sess.add(sch)
        sess.flush()
        assert sch.end == datetime(2026, 1, 1, 6, 15, tzinfo=UTC)


def test_daytime_apply(engine):
    """apply() links a day-time to its day by name."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        sess.add(rain.Day(name="weekend"))
        sess.flush()
        dt = rain.DayTime(descr="sat")
        sess.add(dt)
        dt.apply(day="weekend")
        sess.flush()
        assert dt.day.name == "weekend"
        with pytest.raises(ValueError, match="day"):
            rain.DayTime(descr="x").apply()


def test_envitem_apply(engine):
    """apply() resolves the env group within the site."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")  # provides EnvGroup "std"
        ei = rain.EnvItem()
        sess.add(ei)
        ei.apply(site="home", group="std", temp=12.0)
        sess.flush()
        assert ei.group.name == "std"
        assert ei.temp == 12.0
        with pytest.raises(ValueError, match="group"):
            rain.EnvItem().apply(site="home")
        with pytest.raises(ValueError, match="site"):
            rain.EnvItem().apply()


def test_dayrange_apply_m2m(engine):
    """apply() links/unlinks days by name with a '-' prefix."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        sess.add_all([rain.Day(name="mon"), rain.Day(name="tue")])
        sess.flush()
        dr = rain.DayRange(name="weekdays")
        sess.add(dr)
        dr.apply(days=("mon", "tue"))
        sess.flush()
        assert {d.name for d in dr.days} == {"mon", "tue"}
        dr.apply(days=("-mon",))
        sess.flush()
        assert {d.name for d in dr.days} == {"tue"}


def _valve(sess, name):
    v = rain.Valve(name=name)
    sess.add(v)
    v.apply(**_valve_kwargs())
    sess.flush()
    return v


def test_group_apply_m2m(engine):
    """apply() adds/removes valve objects and day-range names."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        v1 = _valve(sess, "V1")
        v2 = _valve(sess, "V2")
        sess.add_all([rain.DayRange(name="dr1"), rain.DayRange(name="dr2")])
        sess.flush()
        g = rain.Group(name="G")
        sess.add(g)
        g.apply(site="home", valves=(v1, v2), days=("dr1",), xdays=("dr2",))
        sess.flush()
        assert {vv.name for vv in g.valves} == {"V1", "V2"}
        assert {d.name for d in g.days} == {"dr1"}
        assert {d.name for d in g.xdays} == {"dr2"}
        g.apply(rm_valves=(v1,), days=("-dr1",))
        sess.flush()
        assert {vv.name for vv in g.valves} == {"V2"}
        assert g.days == set()
        g.apply(xdays=("-dr2",))
        sess.flush()
        assert g.xdays == set()
        with pytest.raises(ValueError, match="site"):
            rain.Group(name="x").apply()


def test_groupoverride_apply(engine):
    """apply() attaches an override to its group within the site."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        g = rain.Group(name="G")
        sess.add(g)
        g.apply(site="home")
        sess.flush()
        go = rain.GroupOverride(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=3600)
        sess.add(go)
        go.apply(site="home", group="G", allowed=True)
        sess.flush()
        assert go.group.name == "G"
        assert go.allowed is True
        with pytest.raises(ValueError, match="group"):
            rain.GroupOverride(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=3600).apply(
                site="home"
            )


def test_groupadjust_apply(engine):
    """apply() attaches an adjuster to its group within the site."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        g = rain.Group(name="G")
        sess.add(g)
        g.apply(site="home")
        sess.flush()
        ga = rain.GroupAdjust(start=datetime(2026, 1, 1, tzinfo=UTC), factor=1.2)
        sess.add(ga)
        ga.apply(site="home", group="G")
        sess.flush()
        assert ga.group.name == "G"
        assert ga.factor == 1.2


def test_valveoverride_apply(engine):
    """apply() takes the valve as an object (compound key)."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        v = _valve(sess, "V1")
        vo = rain.ValveOverride(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=600)
        sess.add(vo)
        vo.apply(valve=v, running=True)
        sess.flush()
        assert vo.valve.name == "V1"
        assert vo.running is True
        with pytest.raises(ValueError, match="valve"):
            rain.ValveOverride(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=600).apply()


def test_schedule_apply(engine):
    """apply() takes the valve as an object and exposes end."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        v = _valve(sess, "V1")
        sch = rain.Schedule(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=900)
        sess.add(sch)
        sch.apply(valve=v)
        sess.flush()
        assert sch.valve.name == "V1"
        assert sch.end == datetime(2026, 1, 1, 6, 15, tzinfo=UTC)
        with pytest.raises(ValueError, match="valve"):
            rain.Schedule(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=900).apply()


def test_level_apply(engine):
    """apply() takes the valve as an object."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        v = _valve(sess, "V1")
        lv = rain.Level(time=datetime(2026, 1, 1, tzinfo=UTC), level=5.0)
        sess.add(lv)
        lv.apply(valve=v, flow=0.3)
        sess.flush()
        assert lv.valve.name == "V1"
        assert lv.flow == 0.3
        with pytest.raises(ValueError, match="valve"):
            rain.Level(time=datetime(2026, 1, 1, tzinfo=UTC), level=5.0).apply()


def test_log_apply(engine):
    """apply() attaches site/controller by name and valve by object; both clear."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        v = _valve(sess, "V1")
        lg = rain.Log(logger="sched", text="started")
        sess.add(lg)
        lg.apply(site="home", controller="C1", valve=v)
        sess.flush()
        assert lg.site.name == "home"
        assert lg.controller.name == "C1"
        assert lg.valve.name == "V1"
        lg.apply(controller="-", valve=None)  # clear both optional parents
        assert lg.controller is None
        assert lg.valve is None
        lg.apply(text="updated")  # omit controller and valve entirely
        assert lg.text == "updated"
        with pytest.raises(ValueError, match="site"):
            rain.Log(logger="x", text="y").apply()


def test_child_apply_errors(engine):
    """Required-parent None-clears and new-needs-parent raises for children."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        g = rain.Group(name="G")
        sess.add(g)
        g.apply(site="home")
        sess.flush()

        with pytest.raises(ValueError, match="day"):
            rain.DayTime(descr="x").apply(day=None)
        with pytest.raises(ValueError, match="site"):
            rain.EnvItem().apply(site=None)
        with pytest.raises(ValueError, match="group"):
            rain.EnvItem().apply(site="home", group=None)
        with pytest.raises(ValueError, match="site"):
            rain.Group(name="x2").apply(site=None)
        with pytest.raises(ValueError, match="site"):
            rain.GroupOverride(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=3600).apply(
                site=None
            )
        with pytest.raises(ValueError, match="site"):
            rain.GroupOverride(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=3600).apply()
        with pytest.raises(ValueError, match="group"):
            rain.GroupOverride(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=3600).apply(
                site="home", group=None
            )
        with pytest.raises(ValueError, match="site"):
            rain.GroupAdjust(start=datetime(2026, 1, 1, tzinfo=UTC), factor=1.0).apply(site=None)
        with pytest.raises(ValueError, match="site"):
            rain.GroupAdjust(start=datetime(2026, 1, 1, tzinfo=UTC), factor=1.0).apply()
        with pytest.raises(ValueError, match="group"):
            rain.GroupAdjust(start=datetime(2026, 1, 1, tzinfo=UTC), factor=1.0).apply(
                site="home", group=None
            )
        with pytest.raises(ValueError, match="group"):
            rain.GroupAdjust(start=datetime(2026, 1, 1, tzinfo=UTC), factor=1.0).apply(site="home")
        with pytest.raises(ValueError, match="valve"):
            rain.ValveOverride(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=600).apply(
                valve=None
            )
        with pytest.raises(ValueError, match="valve"):
            rain.Schedule(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=900).apply(
                valve=None
            )
        with pytest.raises(ValueError, match="valve"):
            rain.Level(time=datetime(2026, 1, 1, tzinfo=UTC), level=1.0).apply(valve=None)
        with pytest.raises(ValueError, match="site"):
            rain.Log(logger="x", text="y").apply(site=None)


def test_child_apply_update_derives_scope(engine):
    """Updating without re-stating site/parent derives it from the existing link."""
    with Session(engine) as sess, ctx_as(session, Mgr(sess)):
        _seed_site(sess, "home")
        g = rain.Group(name="G")
        sess.add(g)
        g.apply(site="home")
        v = _valve(sess, "V1")
        sess.flush()

        ei = rain.EnvItem()
        sess.add(ei)
        ei.apply(site="home", group="std")
        sess.flush()
        ei.apply(temp=5.0)  # no site → derive from self.group
        assert ei.temp == 5.0

        go = rain.GroupOverride(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=3600)
        sess.add(go)
        go.apply(site="home", group="G")
        sess.flush()
        go.apply(allowed=True)
        assert go.allowed is True

        ga = rain.GroupAdjust(start=datetime(2026, 1, 1, tzinfo=UTC), factor=1.0)
        sess.add(ga)
        ga.apply(site="home", group="G")
        sess.flush()
        ga.apply(factor=1.5)
        assert ga.factor == 1.5

        vo = rain.ValveOverride(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=600)
        sess.add(vo)
        vo.apply(valve=v)
        sess.flush()
        vo.apply(running=True)
        assert vo.running is True

        sch = rain.Schedule(start=datetime(2026, 1, 1, 6, tzinfo=UTC), duration=900)
        sess.add(sch)
        sch.apply(valve=v)
        sess.flush()
        sch.apply(seen=True)
        assert sch.seen is True

        lv = rain.Level(time=datetime(2026, 1, 1, tzinfo=UTC), level=1.0)
        sess.add(lv)
        lv.apply(valve=v)
        sess.flush()
        lv.apply(flow=0.2)
        assert lv.flow == 0.2

        sess.add(rain.Day(name="d"))
        sess.flush()
        dt = rain.DayTime(descr="x")
        sess.add(dt)
        dt.apply(day="d")
        sess.flush()
        dt.apply(descr="y")
        assert dt.descr == "y"
