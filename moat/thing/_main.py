"""
Support for things.
"""

# The main code must not load any sqlalchemy code.
# sqlalchemy might not be present.

from __future__ import annotations

import sys

import asyncclick as click
from sqlalchemy import select

from moat.util import ensure_cfg, load_subgroup, option_ng, yprint
from moat.db import database

from .model import Thing, ThingTyp

ensure_cfg("moat.db")


@load_subgroup(prefix="moat.thing", invoke_without_command=False)
@click.pass_context
@click.option("--name", "-n", type=str, help="Name of the thing type")
def cli(ctx, name):
    """Things."""
    obj = ctx.obj

    sess = ctx.with_resource(database(obj.cfg.db))
    ctx.with_resource(sess.begin())

    obj.session = sess
    obj.name = name


@cli.group
@click.option("--name", "-n", type=str, help="Text on the label")
@click.pass_obj
def one(obj, name):
    """
    Manage actual things.
    """
    obj.name = name
    pass


@one.command(name="show")
@click.option("--type", "-t", "type_", type=str, help="Type of thing to list")
@click.pass_obj
def show_(obj, type_):
    """
    Show thing details / list all things of a type.

    If a name is set, show details for this thing.
    Otherwise list all things without storage.
    """
    sess = obj.session

    if obj.name is not None:
        thing = sess.one(Thing, name=obj.name)
        yprint(thing.dump())
        return

    sel = select(Thing)
    if type_ is None:
        sel = sel.where(Thing.container == None)  # noqa:E711
    else:
        ttyp = obj.session.one(ThingTyp, name=type_)
        sel = sel.where(Thing.thingtyp == ttyp)
    with sess.execute(select(Thing).where(Thing.container == None)) as things:  # noqa:E711
        for (thing,) in things:
            print(thing.name, thing.descr)


def opts(c):
    c = option_ng("--name", "-n", type=str, help="Rename this thing")(c)
    c = option_ng("--x", "-x", "pos_x", type=int, help="X position in parent")(c)
    c = option_ng("--y", "-y", "pos_y", type=int, help="Y position in parent")(c)
    c = option_ng("--z", "-z", "pos_z", type=int, help="Z position in parent")(c)
    c = option_ng("--in", "-i", "container", type=str, help="Where is it?")(c)
    c = option_ng("--typ", "-t", "thingtyp", type=str, help="Type of the thing")(c)
    c = option_ng("--descr", "-d", "descr", type=str, help="Description of the thing")(c)
    c = option_ng("--comment", "-c", type=str, help="Additional comments")(c)
    c = option_ng("--label", "-l", type=str, help="Label for this thing")(c)
    return c


@one.command()
@opts
@click.pass_obj
def add(obj, **kw):
    """
    Add a thing.
    """
    if obj.name is None:
        raise click.UsageError("The thing needs a name!")

    try:
        thing = obj.session.one(Thing, name=obj.name)
    except KeyError:
        pass
    else:
        print("This thing already exists", file=sys.stderr)
        sys.exit(1)
    thing = Thing(name=obj.name)
    obj.session.add(thing)
    thing.apply(**kw)


@one.command(epilog="Use '-x/-y/-z 0' to clear a position, '--in -' to remove the location.")
@opts
@click.pass_obj
def set(obj, **kw):  # noqa: A001
    """
    Modify a thing.
    """
    if obj.name is None:
        raise click.UsageError("Which thing? Use a name")

    try:
        thing = obj.session.one(Thing, name=obj.name)
    except KeyError:
        print("This thing doesn't exist", file=sys.stderr)
        sys.exit(1)
    thing.apply(**kw)


@one.command()
@click.pass_obj
def delete(obj):
    """
    Permanently remove a thing.
    """
    if obj.name is None:
        raise click.UsageError("Which thing? Use a name")
    try:
        thing = obj.session.one(Thing, name=obj.name)
    except KeyError:
        print("This thing doesn't exist", file=sys.stderr)
        sys.exit(1)
    obj.session.delete(thing)


@cli.group(name="typ")
@click.option("--name", "-n", type=str, help="Name of the type")
@click.pass_context
def typ_(ctx, name):
    """\
    Manage a hierarchy of types of things.
    """
    obj = ctx.obj
    if obj.name is not None:
        raise click.UsageError("Please use 'thing typ -n NAME'")
    obj.name = name


@typ_.command(name="show")
@click.pass_obj
def typ_show(obj):
    """
    Show thing details / list all thing types.

    If a name is set, show details for this type.
    Otherwise list all known thing types.
    """
    sess = obj.session

    if obj.name is None:
        seen = False
        with sess.execute(select(ThingTyp)) as things:
            for (thing,) in things:
                seen = True
                print(thing.name)
        if not seen:
            print("No thing types defined yet. Use '--help'?", file=sys.stderr)
    else:
        thing = sess.one(ThingTyp, name=obj.name)
        yprint(thing.dump())


def typopts(c):
    c = option_ng("--name", "-n", type=str, help="Rename this type")(c)
    c = option_ng("--parent", "-p", type=str, help="Parent of this type")(c)
    c = click.option(
        "--abstract",
        "-a",
        is_flag=True,
        help="This type can't contain a real thing",
    )(c)
    c = click.option("--real", "-A", is_flag=True, help="This type can have a real thing")(c)
    c = option_ng("--comment", "-c", "comment", type=str, help="Description of this type")(c)
    return c


@typ_.command(name="add")
@typopts
@click.pass_obj
def typ_add(obj, **kw):
    """
    Add a thing type.
    """
    if obj.name is None:
        raise click.UsageError("The thing type needs a name!")

    bt = ThingTyp(name=obj.name)
    obj.session.add(bt)
    bt.apply(**kw)


@typ_.command(name="set", epilog="Use '-i -NAME' to remove a containing thing type.")
@typopts
@click.pass_obj
def typ_set(obj, **kw):
    """
    Modify a thing type.
    """
    if obj.name is None:
        raise click.UsageError("Which thing type? Use a name")

    bt = obj.session.one(ThingTyp, name=obj.name)
    bt.apply(**kw)


@typ_.command(name="delete")
@click.pass_obj
def typ_delete(obj):
    """
    Remove a thing type.
    """
    if obj.name is None:
        raise click.UsageError("Which thing type? Use a name")
    bt = obj.session.one(ThingTyp, name=obj.name)
    obj.session.delete(bt)
