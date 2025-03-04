"""
Database support.
"""

# The main code must not load any sqlalchemy code.
# sqlalchemy might not be present.

from __future__ import annotations

import anyio
import logging  # pylint: disable=wrong-import-position
import sys
from datetime import datetime
from functools import partial
from time import time
from moat.util import load_subgroup, CFG, ensure_cfg

import asyncclick as click

ensure_cfg("moat.db")


@load_subgroup(prefix="moat.db", invoke_without_command=False)
@click.option("-v","--verbose",is_flag=True,help="Log database commands")
@click.pass_obj
def cli(obj, verbose):
    """Database support"""
    cfg = obj.cfg.db
    cfg.verbose=verbose


@cli.command(name="init")
@click.pass_obj
def init_(obj):
    """\
    Initialize the database.
    """
    from .util import database,load,alembic_cfg
    from alembic import command
    cfg = obj.cfg.db

    meta = load(cfg)
    with database(cfg) as conn:
        meta.create_all(conn.bind)

        acfg = alembic_cfg(cfg, conn)
        command.stamp(acfg, "head")


@cli.command()
@click.pass_obj
def update(obj):
    """
    Migrate the database.
    """
    from .util import database,load, alembic_cfg
    from alembic import command
    cfg = obj.cfg.db

    meta = load(cfg)
    with database(cfg) as sess:
        acfg = alembic_cfg(cfg, sess)

        command.upgrade(acfg, "head")


@cli.command()
@click.argument("args", nargs=-1)
@click.pass_obj
def get(obj, args):
    """
    Read data.
    """
    from .util import database,load
    cfg = obj.cfg.db

    meta = load(cfg)
    with database(cfg) as sess:
        if not args:
            for t in meta.tables.keys():
                print(t)
            return
        t = meta.tables[args[0]]

        if len(args) == 1:
            for c in t.columns:
                print(c.name)
            return

        # TODO


@cli.group
def mig():
    """\
    Database migration commands. Development only!
    """

@mig.command(name="init")
@click.pass_obj
def mig_init(obj):
    """
    Initialize the database migration.

    This should not be necessary, as the normal "init" command will do this.
    """

    from .util import database,load,alembic_cfg
    from alembic import command
    cfg = obj.cfg.db

    meta = load(cfg)
    with database(cfg) as conn:
        acfg = alembic_cfg(cfg, conn)
        command.stamp(acfg, "head")



@mig.command(name="rev")
@click.pass_obj
@click.argument("message", nargs=-1,type=str)
def mig_rev(obj, message):
    """
    Create a new revision.
    """
    from .util import database,load, alembic_cfg
    from alembic import command
    cfg = obj.cfg.db

    if not message:
        raise click.UsageError("You need to add some change text")

    meta = load(cfg)
    with database(cfg) as sess:
        acfg = alembic_cfg(cfg, sess)

        try:
            command.check(acfg)
        except Exception:
            command.revision(acfg, " ".join(message), autogenerate=True)


@mig.command(name="check")
@click.pass_obj
def mig_check(obj):
    """
    Check if a new revision is required.
    """
    from .util import database,load, alembic_cfg
    from alembic import command
    from alembic.util.exc import AutogenerateDiffsDetected
    cfg = obj.cfg.db

    meta = load(cfg)
    with database(cfg) as sess:
        acfg = alembic_cfg(cfg, sess)

        try:
            command.check(acfg)
        except AutogenerateDiffsDetected as exc:
            print(exc)
            sys.exit(1)

