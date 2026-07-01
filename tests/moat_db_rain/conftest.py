"""Shared pytest fixtures for the ``moat.db.rain`` test suite.

A single SQLite database is built once per session (``_db_url`` /
``_engine``); every test reuses it. Per-test isolation is restored by
:func:`db_url`, which wipes the ``rain_*`` rows on exit (dependents
first, so the SQLite ``foreign_keys=ON`` pragma holds).

Two entry points are exposed:

* :func:`rain` — drives the full ``moat`` CLI in-process via
  :func:`moat.src.test.run`, pointing ``moat.db.url`` at the shared DB.
* :func:`engine` — a SQLAlchemy engine bound to the shared DB, for
  tests that talk to the ORM directly.

The seed fixtures (:func:`seed_site`, :func:`seed_valve`,
:func:`seed_group_world`) populate the standard test worlds with direct
ORM inserts — far cheaper than driving the CLI ``add`` commands (each
of which reparses the YAML config tree, ~0.4 s apiece).
"""

from __future__ import annotations

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import moat.db.util  # noqa: F401  — attaches the sqlite ``foreign_keys=ON`` pragma listener
from moat.db.rain import model as rmodel
from moat.db.schema import Base
from moat.db.util import Mgr
from moat.lib.path import Path
from moat.src.test import run


@pytest.fixture(scope="session")
def _db_url(tmp_path_factory):
    """Build one SQLite database with the full schema for the session.

    The ``rain_*`` (and sibling) tables are created once via
    :meth:`MetaData.create_all`; every test reuses this file. Per-test
    isolation is restored by :func:`db_url`, which wipes the ``rain_*``
    rows on exit.
    """
    db_path = tmp_path_factory.mktemp("rain-db") / "r.db"
    url = f"sqlite:///{db_path}"
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    try:
        yield url
    finally:
        eng.dispose()


def _wipe_rain(url: str) -> None:
    """Delete every row from the ``rain_*`` tables (dependents first).

    Tables are cleared in reverse dependency order so foreign-key
    constraints (enforced by the SQLite connect pragma) hold while
    children are removed before their parents.
    """
    eng = create_engine(url)
    try:
        with eng.begin() as conn:
            for tbl in reversed(Base.metadata.sorted_tables):
                if tbl.name.startswith("rain_"):
                    conn.execute(tbl.delete())
    finally:
        eng.dispose()


@pytest.fixture
def db_url(_db_url):
    """The shared DB url; all ``rain_*`` rows are wiped after each test."""
    try:
        yield _db_url
    finally:
        _wipe_rain(_db_url)


@pytest.fixture
def _engine(_db_url):
    """A SQLAlchemy engine bound to the shared DB.

    Fresh per test so no pooled connection retains a stale view of the
    ``db_url`` wipe — the session-scoped engine leaked prior tests' rows
    into later tests under ``pytest-randomly`` ordering.
    """
    eng = create_engine(_db_url)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def engine(_engine, db_url):  # noqa:ARG001
    """The shared engine for ORM-direct tests.

    Depends on :func:`db_url` solely so its per-test wipe fires; the
    engine itself is session-scoped (returned unchanged).
    """
    return _engine


@pytest.fixture
async def rain(db_url):
    """An async ``R()`` caller against the shared session DB."""
    url = db_url

    async def R(*args, ee=0):
        return await run("-s", "moat.db.url", url, *args, expect_exit=ee)

    return R


# --- Seed fixtures (direct ORM; ~100× cheaper than CLI ``add``) --------


@pytest.fixture
def seed_site(engine):
    """Seed a site ``home`` with controller ``C1``, feed ``F1``, env ``std``.

    The env group ``std`` has ``factor=0.8`` and rain gated off
    (``rain=False``), matching the legacy ``--no-rain -f 0.8`` seed.
    """
    with Session(engine) as sess:
        site = rmodel.Site(name="home")
        ctrl = rmodel.Controller(name="C1", site=site, location="shed")
        feed = rmodel.Feed(name="F1", site=site, flow_monitor=Path.from_str("mon.flow"))
        env = rmodel.EnvGroup(name="std", site=site, factor=0.8, rain=False)
        sess.add_all([site, ctrl, feed, env])
        sess.commit()


@pytest.fixture
def seed_valve(seed_site, engine):  # noqa:ARG001
    """Extend :func:`seed_site` with valve ``V1`` on controller ``C1``."""
    with Session(engine) as sess:
        mgr = Mgr(sess)
        site = mgr.one(rmodel.Site, name="home")
        ctrl = mgr.one(rmodel.Controller, name="C1", site=site)
        feed = mgr.one(rmodel.Feed, name="F1", site=site)
        env = mgr.one(rmodel.EnvGroup, name="std", site=site)
        valve = rmodel.Valve(
            name="V1",
            controller=ctrl,
            feed=feed,
            envgroup=env,
            location="front",
            flow=2,
            area=10,
        )
        sess.add(valve)
        sess.commit()


@pytest.fixture
def seed_group_world(engine):
    """Seed a site with two controllers, two valves, and two day ranges.

    Controllers ``C1`` (shed) / ``C2`` (field), feed ``F1``, env ``std``
    (defaults: ``factor=1.0``, ``rain=True``), valves ``V1`` on ``C1``
    and ``V2`` on ``C2``, day ranges ``alldays`` and ``weekends``.
    """
    with Session(engine) as sess:
        site = rmodel.Site(name="home")
        c1 = rmodel.Controller(name="C1", site=site, location="shed")
        c2 = rmodel.Controller(name="C2", site=site, location="field")
        feed = rmodel.Feed(name="F1", site=site, flow_monitor=Path.from_str("mon.flow"))
        env = rmodel.EnvGroup(name="std", site=site)
        v1 = rmodel.Valve(
            name="V1", controller=c1, feed=feed, envgroup=env, location="front", flow=2, area=10
        )
        v2 = rmodel.Valve(
            name="V2", controller=c2, feed=feed, envgroup=env, location="back", flow=3, area=5
        )
        dr1 = rmodel.DayRange(name="alldays")
        dr2 = rmodel.DayRange(name="weekends")
        sess.add_all([site, c1, c2, feed, env, v1, v2, dr1, dr2])
        sess.commit()
