"""
Database support.
"""

from __future__ import annotations

import atexit
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from importlib import import_module
from pathlib import Path

import asyncclick as click
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from moat.util import attrdict, ctx_as, merge
from moat.lib.config import CFG

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.sql.schema import MetaData

logger = logging.getLogger(__name__)

__all__ = ["Session", "alembic_cfg", "database", "dispose", "load", "session"]


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    connection_record  # noqa:B018
    if "sqlite" not in dbapi_connection.__class__.__module__:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


Session = sessionmaker()

session = ContextVar("session")


_loaded = False

# One engine per database URL, reused across calls. Creating a fresh engine
# on every ``load()`` (and thus every ``database()`` / CLI invocation) leaks
# the previous engine and its pooled connections -- they get GC'd mid-session
# and anyio/SQLite reports ``unclosed database``. The idiomatic SQLAlchemy
# pattern is a single engine per process, with many short-lived sessions.
_engines: dict[str, Engine] = {}


def dispose() -> None:
    """Dispose every cached engine and drop it.

    Registered with :mod:`atexit` so connections close cleanly on interpreter
    exit; tests may also call it explicitly at session end.
    """
    while _engines:
        _, eng = _engines.popitem()
        eng.dispose()


atexit.register(dispose)


def load(cfg: attrdict) -> MetaData:
    """Load database models as per config."""
    from moat.db.schema import Base  # noqa: PLC0415

    merge(cfg, CFG.moat.db, replace=False)

    global _loaded
    if not _loaded:
        for schema in cfg.schemas:
            import_module(schema)
        _loaded = True

    # Reuse one engine per URL; the first call's ``echo`` setting wins.
    engine = _engines.get(cfg.url)
    if engine is None:
        engine = create_engine(cfg.url, echo=cfg.get("verbose", False))
        _engines[cfg.url] = engine
    Session.configure(bind=engine)

    return Base.metadata


class Mgr:
    def __init__(self, session):
        self.__session = session

    def __getattr__(self, k):
        return getattr(self.__session, k)

    def one(self, table, **kw):
        """Quick way to retrieve a single result"""
        sel = select(table)
        for k, v in kw.items():
            sel = sel.where(getattr(table, k) == v)
        res = self.__session.execute(sel.limit(2)).fetchall()
        if not res:
            raise KeyError(table.__name__, kw)
        if len(res) != 1:
            raise ValueError("Not unique", table.__name__, kw)
        return res[0][0]


@contextmanager
def database(cfg: attrdict) -> Session:
    """Start a database session."""

    load(cfg)
    try:
        with Session() as conn:
            sess = Mgr(conn)
            with ctx_as(session, sess):
                yield sess
    except click.exceptions.ClickException:
        raise
    except Exception:
        logger.error("On database %r:", getattr(cfg, "url", "?"))
        raise


def alembic_cfg(gcfg, sess):
    """Generate a config object for Alembic."""
    from configparser import RawConfigParser  # noqa:PLC0415,I001
    from alembic.config import Config  # noqa: PLC0415
    from moat import db  # noqa: PLC0415

    cfg = gcfg.moat.db

    c = Config()
    c.file_config = RawConfigParser()
    c.set_section_option("alembic", "script_location", str(Path(db.__path__[0]) / "alembic"))
    # c.set_section_option("alembic", "timezone", gcfg.env.timezone)
    c.set_section_option("alembic", "file_template", "%(rev)s")
    c.set_section_option("alembic", "version_path_separator", "os")

    c.attributes["session"] = sess
    c.attributes["connection"] = sess.connection()
    c.attributes["metadata"] = load(cfg)
    c.attributes["config"] = cfg

    return c
