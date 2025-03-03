"""
Database support.
"""

from __future__ import annotations

from pathlib import Path
from moat.util import ensure_cfg
from importlib import import_module
from contextlib import contextmanager

from sqlalchemy import Connection, create_engine

import logging
logger=logging.getLogger(__name__)


ensure_cfg("moat.db")

_loaded = False
def load(cfg) -> metadata:
    """Load database models as per config."""
    from moat.db.schema import Base

    global _loaded
    if not _loaded:
        for schema in cfg.schemas:
            import_module(schema)
        _loaded = True

    return Base.metadata


@contextmanager
def database(cfg):
    """Load database models as per config."""

    engine = create_engine(cfg.url, echo=False)
    with Connection(engine) as conn:
        yield conn
    logger.info("Done.")

def alembic_cfg(cfg, conn):
    """Generate a config object for Alembic."""
    from alembic.config import Config
    from configparser import RawConfigParser
    from moat import db

    c = Config()
    c.file_config=RawConfigParser()
    c.set_section_option("alembic","script_location", str(Path(db.__path__[0])/"alembic"))
    c.attributes['connection'] = conn
    c.attributes['metadata'] = load(cfg)

    return c
