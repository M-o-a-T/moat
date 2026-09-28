"""Shared pytest fixtures for the ``moat.db.src`` test suite.

A single SQLite database is built once per session (``_db_url`` /
``_engine``); every test reuses it. Per-test isolation is restored by
:func:`db_url`, which wipes the ``src_*`` rows on exit (dependents first,
so the SQLite ``foreign_keys=ON`` pragma holds).

Two entry points are exposed:

* :func:`src` — drives the full ``moat`` CLI in-process via
  :func:`moat.src.test.run`, pointing ``moat.db.url`` at the shared DB.
* :func:`engine` — a SQLAlchemy engine bound to the shared DB, for tests
  that talk to the ORM directly.

Roles are seeded cheaply with direct ORM inserts (:func:`seed_roles`) so
the registry-driven leaves don't each pay for a CLI ``archive add``.
"""

from __future__ import annotations

import os
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Importing the model modules populates ``Base.metadata`` with the
# ``src_*`` tables and wires their relationships.
import moat.db.src.model  # noqa: F401
import moat.db.src.model_  # noqa: F401
import moat.db.util  # noqa: F401  — attaches the sqlite ``foreign_keys=ON`` pragma listener
from moat.db.schema import Base
from moat.db.src.model import ArchiveRole, BranchRole
from moat.db.util import load_schemas
from moat.src.test import run


def pytest_configure(config):  # noqa: ARG001
    """Scrub pre-commit's ``GIT_*`` env leakage for the whole session.

    Pre-commit stages files with ``GIT_DIR``/``GIT_INDEX_FILE``/etc.
    pointing at the main repo's staging area; if inherited, every ``git``
    subprocess (including those spawned inside the CLI by
    :mod:`moat.db.src._git`) would act on the wrong work tree. Dropping
    them once at session start lets the import/export tests build and
    probe throwaway repos reliably. Production callers never see this.
    """
    for k in list(os.environ):
        if k.startswith("GIT_"):
            del os.environ[k]


@pytest.fixture(scope="session")
def _db_url(tmp_path_factory):
    """Build one SQLite database with the full schema for the session."""
    db_path = tmp_path_factory.mktemp("src-db") / "s.db"
    url = f"sqlite:///{db_path}"
    eng = create_engine(url)
    load_schemas().create_all(eng)
    try:
        yield url
    finally:
        eng.dispose()


def _wipe_src(url: str) -> None:
    """Delete every row from the ``src_*`` tables (dependents first)."""
    eng = create_engine(url)
    try:
        with eng.begin() as conn:
            for tbl in reversed(Base.metadata.sorted_tables):
                if tbl.name.startswith("src_"):
                    conn.execute(tbl.delete())
    finally:
        eng.dispose()


@pytest.fixture
def db_url(_db_url):
    """The shared DB url; all ``src_*`` rows are wiped after each test."""
    try:
        yield _db_url
    finally:
        _wipe_src(_db_url)


@pytest.fixture
def _engine(_db_url):
    """A fresh-per-test SQLAlchemy engine bound to the shared DB."""
    eng = create_engine(_db_url)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def engine(_engine, db_url):  # noqa: ARG001
    """The shared engine for ORM-direct tests (wiped per test via db_url)."""
    return _engine


@pytest.fixture
async def src(db_url):
    """An async ``R()`` caller against the shared session DB."""

    url = db_url

    async def R(*args, ee=0):
        return await run("-s", "moat.db.url", url, "db", "src", *args, expect_exit=ee)

    return R


@pytest.fixture
def seed_roles(engine):
    """Seed the standard archive + branch role vocabularies via direct ORM.

    Cheaper than driving the CLI ``archive add`` / ``branch add`` for
    every test that needs the registries populated.
    """
    with Session(engine) as sess:
        arcs = [
            ArchiveRole(name="upstream", rank=1),
            ArchiveRole(name="fork", rank=2),
            ArchiveRole(name="mirror", rank=3),
            ArchiveRole(name="local", rank=4),
            ArchiveRole(name="internal", rank=5),
        ]
        brs = [
            BranchRole(name="main"),
            BranchRole(name="release"),
            BranchRole(name="feature", abstract=True),
        ]
        sess.add_all(arcs + brs)
        sess.commit()
