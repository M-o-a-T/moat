"""
Support for boxes for storing things.
"""

# The main code must not load any sqlalchemy code.
# sqlalchemy might not be present.

from __future__ import annotations

import sys

import asyncclick as click
from sqlalchemy import select

from moat.util import ensure_cfg, load_subgroup, option_ng, yprint
from moat.db import database

from .model import Box, BoxTyp

ensure_cfg("moat.db")


@load_subgroup(prefix="moat.box", invoke_without_command=False)
@click.pass_context
def cli(ctx):
    """Boxes for storing things."""
    obj = ctx.obj

    sess = ctx.with_resource(database(obj.cfg.db))
    ctx.with_resource(sess.begin())

    obj.session = sess


@cli.group
@click.option("--name", "-n", type=str, help="Text on the label")
@click.pass_obj
def one(obj, name):
    """
    Manage boxes.
    """
    obj.name = name
    pass


@one.command(name="show")
@click.pass_obj
def show_(obj):
    """
    Show box details / list all box types.

    If a name is set, show details for this box.
    Otherwise list all boxes without parents.
    """
    sess = obj.session

    if obj.name is None:
        seen = False
        with sess.execute(select(Box).where(Box.container == None)) as boxes:  # noqa:E711
            for (box,) in boxes:
                seen = True
                print(box.name)
        if not seen:
            print("No box types defined yet. Use '--help'?", file=sys.stderr)
    else:
        box = sess.one(Box, name=obj.name)
        yprint(box.dump())


def opts(c):
    c = option_ng("--name", "-n", type=str, help="Rename this box")(c)
    c = option_ng("--x", "-x", "pos_x", type=int, help="X position in parent")(c)
    c = option_ng("--y", "-y", "pos_y", type=int, help="Y position in parent")(c)
    c = option_ng("--z", "-z", "pos_z", type=int, help="Z position in parent")(c)
    c = option_ng("--in", "-i", "container", type=str, help="Where is it?")(c)
    c = option_ng("--typ", "-t", "boxtyp", type=str, help="Type of the box")(c)
    return c


@one.command()
@opts
@click.pass_obj
def add(obj, **kw):
    """
    Add a box.
    """
    if obj.name is None:
        raise click.UsageError("The box needs a name!")

    try:
        box = obj.session.one(Box, name=obj.name)
    except KeyError:
        pass
    else:
        print("This box already exists", file=sys.stderr)
        sys.exit(1)
    box = Box(name=obj.name)
    obj.session.add(box)
    box.apply(**kw)


@one.command(epilog="Use '-in -' to drop the parent box, -x/-y/-z 0 to clear a position.")
@opts
@click.pass_obj
def set(obj, **kw):  # noqa:A001
    """
    Modify a box.
    """
    if obj.name is None:
        raise click.UsageError("Which box? Use a name")

    try:
        box = obj.session.one(Box, name=obj.name)
    except KeyError:
        print("This box doesn't exist", file=sys.stderr)
        sys.exit(1)
    box.apply(**kw)


@one.command()
@click.pass_obj
def delete(obj):
    """
    Remove a box.
    """
    if obj.name is None:
        raise click.UsageError("Which box? Use a name")
    try:
        box = obj.session.one(Box, name=obj.name)
    except KeyError:
        print("This box doesn't exist", file=sys.stderr)
        sys.exit(1)
    obj.session.delete(box)


@cli.group(name="typ")
@click.option("--name", "-n", type=str, help="Name of the box type")
@click.pass_context
def typ_(ctx, name):
    """\
    Manage box types.
    """
    obj = ctx.obj
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
            for (box,) in boxes:
                seen = True
                print(box.name)
        if not seen:
            print("No box types defined yet. Use '--help'?", file=sys.stderr)
    else:
        box = sess.one(BoxTyp, name=obj.name)
        yprint(box.dump())


def typopts(c):
    c = option_ng("--name", "-n", type=str, help="Rename this type")(c)
    c = option_ng("--x", "-x", "pos_x", type=int, help="Number of X positions for content")(c)
    c = option_ng("--y", "-y", "pos_y", type=int, help="Number of Y positions for content")(c)
    c = option_ng("--z", "-z", "pos_z", type=int, help="Number of Z positions for content")(c)
    c = option_ng("--comment", "-c", "comment", type=str, help="Description of this type")(c)
    c = click.option(
        "--in",
        "-i",
        "parent",
        type=str,
        multiple=True,
        help="Where can you put this thing into?",
    )(c)
    c = click.option("--usable", "-u", is_flag=True, help="Things can be put into this box")(c)
    c = click.option("--unusable", "-U", is_flag=True, help="The box holds fixed subdividers")(c)
    return c


@typ_.command(name="add")
@typopts
@click.pass_obj
def typ_add(obj, parent, **kw):
    """
    Add a box type.
    """
    parent  # noqa:B018

    if obj.name is None:
        raise click.UsageError("The box type needs a name!")

    bt = BoxTyp(name=obj.name)
    obj.session.add(bt)
    bt.apply(**kw)


@typ_.command(name="set", epilog="Use '-i -NAME' to remove a containing box type.")
@typopts
@click.pass_obj
def typ_set(obj, **kw):
    """
    Modify a box type.
    """
    if obj.name is None:
        raise click.UsageError("Which box type? Use a name")

    bt = obj.session.one(BoxTyp, name=obj.name)
    bt.apply(**kw)


@typ_.command(name="delete")
@click.pass_obj
def typ_delete(obj):
    """
    Remove a box type.
    """
    if obj.name is None:
        raise click.UsageError("Which box type? Use a name")
    bt = obj.session.one(BoxTyp, name=obj.name)
    obj.session.delete(bt)
