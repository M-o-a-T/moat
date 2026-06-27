"""Round-trip tests for the Phase-2 leaf models of ``moat.db.rain``."""

from __future__ import annotations

import pytest
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import moat.db.util  # noqa: F401  — attaches the sqlite ``foreign_keys=ON`` pragma listener
from moat.db.rain import model as rain
from moat.db.schema import Base
from moat.lib.path import Path


@pytest.fixture
def engine(tmp_path):
    """A throwaway sqlite engine with the rain schema materialized."""
    eng = create_engine(f"sqlite:///{tmp_path}/rain.db")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def test_site_defaults_and_timedelta(engine):
    """Site fills in its defaults and exposes ``rain_delay`` as a timedelta."""
    with Session(engine) as sess:
        site = rain.Site(name="home")
        sess.add(site)
        sess.flush()
        assert site.rate == 10.0
        assert site.rain_delay == 300
        assert site.rain_delay_td == timedelta(seconds=300)
        assert site.comment is None
        assert site.var is None


def test_envgroup_envitem_relationships(engine):
    """EnvGroup↔EnvItem link bidirectionally and inherit defaults."""
    with Session(engine) as sess:
        site = rain.Site(name="home")
        eg = rain.EnvGroup(name="std", site=site)
        ei = rain.EnvItem(factor=0.5, group=eg)
        sess.add(ei)
        sess.flush()
        assert eg.site is site
        assert site.envgroups == {eg}
        assert ei.group is eg
        assert eg.items == {ei}
        assert eg.factor == 1.0
        assert eg.rain is True
        assert ei.factor == 0.5


def test_day_daytime_unique(engine):
    """Day↔DayTime link and ``(day, descr)`` is unique."""
    with Session(engine) as sess:
        d = rain.Day(name="weekend")
        dt = rain.DayTime(descr="Sat", day=d)
        sess.add(dt)
        sess.flush()
        assert dt.day is d
        assert d.times == {dt}
        sess.add(rain.DayTime(descr="Sat", day=d))
        with pytest.raises(IntegrityError):
            sess.flush()
        sess.rollback()


def test_sensor_kinds_and_unique(engine):
    """Sensors of differing kinds coexist; ``(site, kind, name)`` is unique."""
    with Session(engine) as sess:
        site = rain.Site(name="home")
        m1 = rain.Sensor(kind="rain", name="r1", state=Path.from_str("home.rain"), site=site)
        m2 = rain.Sensor(kind="temp", name="t1", state=Path.from_str("home.temp"), site=site)
        sess.add_all([m1, m2])
        sess.flush()
        assert site.sensors == {m1, m2}
        assert m1.weight == 10
        assert m1.state == Path.from_str("home.rain")
        sess.add(rain.Sensor(kind="rain", name="r1", state=Path.from_str("dup"), site=site))
        with pytest.raises(IntegrityError):
            sess.flush()
        sess.rollback()


def test_feed_defaults_and_timedelta(engine):
    """Feed fills defaults and exposes ``max_flow_wait`` as a timedelta."""
    with Session(engine) as sess:
        site = rain.Site(name="home")
        feed = rain.Feed(name="main", site=site)
        sess.add(feed)
        sess.flush()
        assert feed.flow == 10.0
        assert feed.max_flow_wait == 300
        assert feed.max_flow_wait_td == timedelta(seconds=300)
        assert feed.disabled is False
        assert feed.var is None
        assert site.feeds == {feed}


def test_feed_unique_site_name(engine):
    """``(site, name)`` is unique per feed."""
    with Session(engine) as sess:
        site = rain.Site(name="home")
        sess.add_all([rain.Feed(name="main", site=site), rain.Feed(name="main", site=site)])
        with pytest.raises(IntegrityError):
            sess.flush()
        sess.rollback()


def test_cascade_delete_site_removes_children(engine):
    """Deleting a site cascades to its envgroups, sensors, and feeds.

    Mirrors a one-shot ``delete`` command: the deleting session loads only
    the site (the collections are lazy), so SQLAlchemy's ``passive_deletes``
    lets the database ``ON DELETE CASCADE`` handle the children.
    """
    with Session(engine) as sess:
        site = rain.Site(name="home")
        eg = rain.EnvGroup(name="std", site=site)
        sensor = rain.Sensor(kind="rain", name="r1", state=Path.from_str("home.rain"), site=site)
        feed = rain.Feed(name="main", site=site)
        sess.add_all([eg, sensor, feed])
        sess.flush()
        eg_id, sensor_id, feed_id, site_id = eg.id, sensor.id, feed.id, site.id
        sess.commit()

    with Session(engine) as sess:
        sess.delete(sess.get(rain.Site, site_id))
        sess.commit()

    with Session(engine) as sess:
        assert sess.get(rain.EnvGroup, eg_id) is None
        assert sess.get(rain.Sensor, sensor_id) is None
        assert sess.get(rain.Feed, feed_id) is None
