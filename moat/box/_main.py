"""
Support for boxes for storing things.
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
from moat.util import load_subgroup, CFG, ensure_cfg, yprint
from moat.db import database
from .model import Box,BoxTyp
from sqlalchemy import select

import asyncclick as click

ensure_cfg("moat.db")


@load_subgroup(prefix="moat.box", invoke_without_command=False)
@click.pass_obj
def cli(obj):
    """Boxes for storing things."""


@cli.group(name="typ")
@click.option("--name","-n",type=str,help="Name of the box type")
@click.pass_obj
def typ_(obj,name):
    """\
    Manage box types.
    """
    obj.name=name


@typ_.command(name="show")
@click.pass_obj
def show_(obj):
    """
    List all box types.

    If a name is set, show details for this type.
    """
    with database(obj.cfg.db) as sess, sess.begin():
        if obj.name is None:
            seen = False
            with sess.execute(select(BoxTyp)) as boxes:
                for box, in boxes:
                    seen = True
                    print(box.name)
            if not seen:
                print("No box types defined yet. Use '--help'?", file=sys.stderr)
        else:
            box = sess.one(BoxTyp, name=obj.name)
            yprint(box.dump())

def opts(c):
    c = click.option("--x","-x","pos_x",type=int,help="Number of X positions for content")(c)
    c = click.option("--y","-y","pos_y",type=int,help="Number of Y positions for content")(c)
    c = click.option("--z","-z","pos_z",type=int,help="Number of Z positions for content")(c)
    c = click.option("--comment","-c","comment",type=str,help="Description of this type")(c)
    c = click.option("--parent","-p","parent",type=str,help="Where can you put this thing into? (Prefix with '-' to remove)")(c)
    return c

@typ_.command()
@opts
@click.pass_obj
def add(obj, parent, **kw):
    """
    Add a box type.
    """
    if obj.name is None:
        raise click.UsageError("The box type needs a name!")
    with database(obj.cfg.db) as sess, sess.begin():
        bt = BoxTyp(name=obj.name)
        for k,v in kw.items():
            if v is not None:
                setattr(bt,k,v)
        if parent is not None:
            bt.parents.add(sess.one(BoxType,name=parent))
        sess.add(bt)
        pass

@typ_.command()
@opts
@click.pass_obj
def set(obj, parent, **kw):
    """
    Modify a box type.
    """
    if obj.name is None:
        raise click.UsageError("The box type needs a name!")
    with database(obj.cfg.db) as sess, sess.begin():
        bt = sess.execute(select(BoxTyp).where(BoxTyp.name==obj.name)).first()
        if not bt:
            raise ValueError(f"Box type {obj.name !r} not found")
        bt = bt[0]

        for k,v in kw.items():
            if v is not None:
                setattr(bt,k,v)

        if parent is not None:
            if parent[0] == "-":
                bt.parents.remove(sess.one(BoxType,name=parent[1:]))
            else:
                bt.parents.add(sess.one(BoxType,name=parent))

@typ_.command()
def delete(**kw):
    """
    Remove a box type.
    """
    with database(obj.cfg.db) as sess, sess.begin():
        pass
