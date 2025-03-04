"""
Database support.
"""

from __future__ import annotations

from pathlib import Path
from moat.util import ensure_cfg, CFG, merge
from importlib import import_module
from contextlib import contextmanager

from sqlalchemy import Connection, create_engine
from sqlalchemy.orm import Session

import logging
logger=logging.getLogger(__name__)


ensure_cfg("moat.db")

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

    return Base.metadata

@contextmanager
def database(cfg:attrdict) -> Session:
    """Start a database session."""

    merge(cfg,CFG.db, replace=False)

    engine = create_engine(cfg.url, echo=cfg.get("verbose",False))
    with Session(engine) as conn:
        yield conn

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
