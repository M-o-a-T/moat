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
import moat.label.model
from .model import Box,BoxTyp
from sqlalchemy import select

import asyncclick as click

ensure_cfg("moat.db")


@load_subgroup(prefix="moat.box", invoke_without_command=False)
@click.pass_context
@click.option("--name","-n",type=str,help="Name of the box type")
def cli(ctx, name):
    """Boxes for storing things."""
    obj = ctx.obj

    sess = ctx.with_resource(database(obj.cfg.db))
    ctx.with_resource(sess.begin())

    obj.session = sess
    obj.name=name


@cli.command(name="show")
@click.pass_obj
def show_(obj):
    """
    Show box details / list all box types.

    If a name is set, show details for this type.
    Otherwise list all boxes withoout parents.
    """
    sess = obj.session

    if obj.name is None:
        seen = False
        with sess.execute(select(Box).where(Box.container==None)) as boxes:
            for box, in boxes:
                seen = True
                print(box.name)
        if not seen:
            print("No box types defined yet. Use '--help'?", file=sys.stderr)
    else:
        box = sess.one(Box, name=obj.name)
        yprint(box.dump())

def opts(c):
    c = click.option("--x","-x","pos_x",type=int,help="X position in parent")(c)
    c = click.option("--y","-y","pos_y",type=int,help="Y position in parent")(c)
    c = click.option("--z","-z","pos_z",type=int,help="Z position in parent")(c)
    c = click.option("--in","-i","container",type=str,help="Where is it?")(c)
    c = click.option("--typ","-t","typ",type=str,help="Type of the box")(c)
    return c

@cli.command()
@opts
@click.pass_obj
def add(obj, container, typ, **kw):
    """
    Add a box.
    """
    if obj.name is None:
        raise click.UsageError("The box needs a name!")

    if typ is None:
        raise click.UsageError("A new box needs a type!")

    box = Box(name=obj.name)
    for k,v in kw.items():
        if v is not None:
            if k.startswith("pos_") and v == 0:
                v = None
            setattr(box,k,v)
    if container:
        box.container = sess.one(Box,name=p)

    obj.session.add(box)

@cli.command(epilog="Use '-in -' to drop the parent box, -x/-y/-z 0 to clear a position.")
@opts
@click.pass_obj
def set(obj, container, **kw):
    """
    Modify a box.
    """
    if obj.name is None:
        raise click.UsageError("The box type needs a name!")

    box = obj.session.one(Box, name=obj.name)

    for k,v in kw.items():
        if v is not None:
            if k.startswith("pos_") and v == 0:
                v = None
            setattr(box,k,v)

    if container:
        box.container = sess.one(Box,name=p)


@cli.command()
@click.pass_obj
def delete(obj):
    """
    Remove a box.
    """
    box = obj.session.one(Box, name=obj.name)
    obj.session.delete(box)


@cli.group(name="typ")
@click.option("--name","-n",type=str,help="Name of the box type")
@click.pass_obj
def typ_(obj, name):
    """\
    Manage box types.
    """
    if obj.name is not None:
        raise click.UsageError("Name a type with 'moat box typ -n …'")
    obj.name = name


@typ_.command(name="show")
@click.pass_obj
def typ_show(obj):
    """
    Show box details / list all box types.

    If a name is set, show details for this type.
    Otherwise list all known box types.
    """
    sess = obj.session

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

def typopts(c):
    c = click.option("--x","-x","pos_x",type=int,help="Number of X positions for content")(c)
    c = click.option("--y","-y","pos_y",type=int,help="Number of Y positions for content")(c)
    c = click.option("--z","-z","pos_z",type=int,help="Number of Z positions for content")(c)
    c = click.option("--comment","-c","comment",type=str,help="Description of this type")(c)
    c = click.option("--parent","-p","parent",type=str,multiple=True,help="Where can you put this thing into?")(c)
    return c

@typ_.command(name="add")
@typopts
@click.pass_obj
def typ_add(obj, parent, **kw):
    """
    Add a box type.
    """
    if obj.name is None:
        raise click.UsageError("The box type needs a name!")

    bt = BoxTyp(name=obj.name)
    for k,v in kw.items():
        if v is not None:
            setattr(bt,k,v)
    for p in parent:
        bt.parents.add(sess.one(BoxType,name=p))
    obj.session.add(bt)
    pass

@typ_.command(name="set", epilog="Use '-p -NAME' to remove a parent.")
@typopts
@click.pass_obj
def typ_set(obj, parent, **kw):
    """
    Modify a box type.
    """
    if obj.name is None:
        raise click.UsageError("The box type needs a name!")

    bt = obj.session.one(BoxTyp, name=obj.name)

    for k,v in kw.items():
        if v is not None:
            setattr(bt,k,v)

    for p in parent:
        if p[0] == "-":
            bt.parents.remove(sess.one(BoxType,name=p[1:]))
        else:
            bt.parents.add(sess.one(BoxType,name=p))


@typ_.command(name="delete")
@click.pass_obj
def typ_delete(obj):
    """
    Remove a box type.
    """
    bt = obj.session.one(BoxTyp, name=obj.name)
    obj.session.delete(bt)

