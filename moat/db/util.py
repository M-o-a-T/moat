"""
Database support.
"""

from __future__ import annotations

from pathlib import Path
from moat.util import ensure_cfg, CFG, merge
from importlib import import_module
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import Connection, create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine


import logging
logger=logging.getLogger(__name__)

__all__ = ["Session","session","load","database","alembic_cfg"]

ensure_cfg("moat.db")


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" not in dbapi_connection.__class__.__name__:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


Session = sessionmaker()

session = ContextVar("session")


_loaded = False
def load(cfg:attrdict) -> metadata:
    """Load database models as per config."""
    from moat.db.schema import Base
    merge(cfg,CFG.db, replace=False)

    global _loaded
    if not _loaded:
        for schema in cfg.schemas:
            import_module(schema)
        _loaded = True

    engine = create_engine(cfg.url, echo=cfg.get("verbose",False))
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
        for k,v in kw.items():
            sel = sel.where(getattr(table,k) == v)
        res = self.__session.execute(sel.limit(2)).fetchall()
        if not res:
            raise KeyError(table.__name__,kw)
        if len(res) != 1:
            raise ValueError("Not unique", table.__name__,kw)
        return res[0][0]


@contextmanager
def database(cfg:attrdict) -> Session:
    """Start a database session."""

    load(cfg)

    with Session() as conn:
        sess = Mgr(conn)
        token = session.set(sess)
        try:
            yield sess
        finally:
            session.reset(token)

def alembic_cfg(gcfg, sess):
    """Generate a config object for Alembic."""
    from alembic.config import Config
    from configparser import RawConfigParser
    from moat import db

    cfg=gcfg.db

    c = Config()
    c.file_config=RawConfigParser()
    c.set_section_option("alembic","script_location", str(Path(db.__path__[0])/"alembic"))
    c.set_section_option("alembic","timezone", gcfg.env.timezone)
    c.set_section_option("alembic","file_template", "%(rev)s")
    c.set_section_option("alembic","version_path_separator", "os")

    c.attributes['session'] = sess
    c.attributes['connection'] = sess.connection()
    c.attributes['metadata'] = load(cfg)
    c.attributes['config'] = cfg

    return c
