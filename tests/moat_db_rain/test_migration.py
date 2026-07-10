"""Alembic round-trip test for the ``moat.db.rain`` migration.

The migration (``9a3f1c7e4b2d``) is validated in isolation: an empty SQLite
database is stamped at the predecessor head (``dd1007d00e262b5c``), upgraded
to the rain revision, and the reflected schema is compared column-for-column
against :data:`moat.db.schema.Base.metadata`. A subsequent downgrade must
remove every ``rain_*`` table.

Stamping past the earlier box/thing/label revisions lets the test sidestep
their ``ALTER``-based steps, which SQLite cannot run outside batch mode; the
rain migration itself uses only ``create_table`` / ``create_index`` / ``drop``
and is fully SQLite-safe.
"""

from __future__ import annotations

from configparser import RawConfigParser
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, create_engine, inspect

import moat.db as dbmod
import moat.db.rain.model  # noqa: F401  — populate the rain tables on the shared metadata
import moat.db.rain.model_  # noqa: F401
import moat.db.util  # noqa: F401  — installs the SQLite ``foreign_keys=ON`` pragma listener
from moat.db.schema import Base

PREV = "dd1007d00e262b5c"
REV = "9a3f1c7e4b2d"


def _alembic(conn) -> Config:
    """Build an Alembic config bound to ``conn`` with the shared script tree."""
    cfg = Config()
    cfg.file_config = RawConfigParser()
    cfg.set_section_option("alembic", "script_location", str(Path(dbmod.__path__[0]) / "alembic"))
    cfg.set_section_option("alembic", "file_template", "%(rev)s")
    cfg.set_section_option("alembic", "version_path_separator", "os")
    cfg.attributes["connection"] = conn
    cfg.attributes["metadata"] = Base.metadata
    return cfg


def _meta_fks(tbl):
    """Foreign keys of a metadata table as comparable tuples."""
    out = set()
    for con in tbl.constraints:
        if not isinstance(con, ForeignKeyConstraint):
            continue
        els = con.elements
        out.add((
            con.name,
            frozenset(el.parent.name for el in els),
            els[0].column.table.name,
            frozenset(el.column.name for el in els),
            els[0].ondelete,
        ))
    return out


def _refl_fks(insp, tname):
    """Foreign keys of a reflected table as comparable tuples."""
    out = set()
    for fk in insp.get_foreign_keys(tname):
        out.add((
            fk["name"],
            frozenset(fk["constrained_columns"]),
            fk["referred_table"],
            frozenset(fk["referred_columns"]),
            fk.get("options", {}).get("ondelete"),
        ))
    return out


def _meta_uqs(tbl):
    """Unique constraints of a metadata table as comparable tuples."""
    return {
        (con.name, frozenset(c.name for c in con.columns))
        for con in tbl.constraints
        if isinstance(con, UniqueConstraint)
    }


def _refl_uqs(insp, tname):
    """Unique constraints of a reflected table as comparable tuples."""
    return {(u["name"], frozenset(u["column_names"])) for u in insp.get_unique_constraints(tname)}


def _compare_table(eng, tbl, tname):
    """Assert a reflected table matches its metadata definition."""
    insp = inspect(eng)
    dia = eng.dialect

    refl_cols = {
        c["name"]: (c["nullable"], c["type"].compile(dialect=dia)) for c in insp.get_columns(tname)
    }
    meta_cols = {c.name: (c.nullable, c.type.compile(dialect=dia)) for c in tbl.columns}
    assert refl_cols == meta_cols, f"columns of {tname}"

    refl_pk = frozenset(insp.get_pk_constraint(tname)["constrained_columns"])
    meta_pk = frozenset(c.name for c in tbl.primary_key.columns)
    assert refl_pk == meta_pk, f"primary key of {tname}"

    assert _refl_fks(insp, tname) == _meta_fks(tbl), f"foreign keys of {tname}"
    assert _refl_uqs(insp, tname) == _meta_uqs(tbl), f"unique constraints of {tname}"

    refl_ix = {
        (ix["name"], frozenset(ix["column_names"]), bool(ix["unique"]))
        for ix in insp.get_indexes(tname)
    }
    meta_ix = {
        (ix.name, frozenset(c.name for c in ix.columns), bool(ix.unique)) for ix in tbl.indexes
    }
    assert refl_ix == meta_ix, f"indexes of {tname}"


def test_rain_migration_round_trip(tmp_path):
    """Upgrade creates the rain schema; downgrade removes it again."""
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    conn = eng.connect()
    acfg = _alembic(conn)

    command.stamp(acfg, PREV)
    conn.commit()
    command.upgrade(acfg, REV)
    conn.commit()

    expected = {t for t in Base.metadata.tables if t.startswith("rain_")}
    try:
        insp = inspect(eng)
        reflected = {t for t in insp.get_table_names() if t.startswith("rain_")}
        assert reflected == expected
        for tname in sorted(expected):
            _compare_table(eng, Base.metadata.tables[tname], tname)
    finally:
        command.downgrade(acfg, PREV)
        conn.commit()
        conn.close()

    insp = inspect(eng)
    assert not [t for t in insp.get_table_names() if t.startswith("rain_")]
    eng.dispose()
