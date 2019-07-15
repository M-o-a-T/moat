# command line interface

import os
import sys
import trio_click as click
from pprint import pprint
import json
import yaml

from distkv.util import (
    attrdict,
    PathLongener,
    MsgReader,
    PathShortener,
    split_one,
    NotGiven,
)
from distkv.client import open_client, StreamedRequest
from distkv.command import Loader
from distkv.default import CFG
from distkv.server import Server
from distkv.auth import loader, gen_auth
from distkv.exceptions import ClientError
from distkv.util import yprint

import logging

logger = logging.getLogger(__name__)


@main.group()
@click.pass_obj
async def cli(obj):
    """Manage types and type matches. Usage: … type …"""
    pass


@cli.command()
@click.option(
    "-s", "--script", type=click.File(mode="w", lazy=True), help="Save the script here"
)
@click.option(
    "-S", "--schema", type=click.File(mode="w", lazy=True), help="Save the schema here"
)
@click.option("-y", "--yaml", "yaml_", is_flag=True, help="Write schema as YAML. Default: JSON.")
@click.argument("path", nargs=-1)
@click.pass_obj
async def get(obj, path, script, schema, yaml_):
    """Read type checker information"""
    if not path:
        raise click.UsageError("You need a non-empty path.")
    res = await obj.client._request(
        action="get_internal",
        path=("type",) + path,
        iter=False,
        nchain=3 if obj.meta else 0,
    )
    r = res.value
    if not obj.meta:
        res = res.value
    if script:
        script.write(r.pop('code'))
    if schema:
        if yaml_:
            yprint(r.pop('schema'), file=schema)
        else:
            json.dump(r.pop('schema'), schema)
    yprint(res)


@cli.command()
@click.option("-g", "--good", multiple=True, help="Example for passing values")
@click.option("-b", "--bad", multiple=True, help="Example for failing values")
@click.option("-d", "--data", "data", type=click.File(mode="r"), help="Load metadata from this YAML file.")
@click.option(
    "-s", "--script", type=click.File(mode="r"), help="File with the checking script"
)
@click.option(
    "-S", "--schema", type=click.File(mode="r"), help="File with the JSON schema"
)
@click.option("-y", "--yaml", is_flag=True, help="load the schema as YAML. Default: JSON")
@click.option(
    "-c",
    "--chain",
    type=int,
    default=0,
    help="Length of change list to return. Default: 0",
)
@click.argument("path", nargs=-1)
@click.pass_obj
async def set(obj, path, chain, good, bad, script, schema, yaml_, data):
    """Write type checker information."""
    if not path:
        raise click.UsageError("You need a non-empty path.")

    if data:
        msg = yaml.safe_load(data)
    else:
        msg = {}
    if "value" in msg:
        chain = msg.get('chain', chain)
        msg = msg['value']
    msg.setdefault("good", [])
    msg.setdefault("bad", [])
    for x in good:
        msg["good"].append(eval(x))
    for x in bad:
        msg["bad"].append(eval(x))

    if "code" in msg:
        if script:
            raise click.UsageError("Duplicate script")
    else:
        if not script:
            raise click.UsageError("Missing script")
        msg["code"] = script.read()

    if "schema" in msg:
        raise click.UsageError("Missing schema")
    else:
        if not schema:
            raise click.UsageError("Missing schema")
        if yaml_:
            msg["schema"] = yaml.safe_load(schema)
        else:
            msg["schema"] = json.load(schema)

    if len(msg['good']) < 2:
        raise click.UsageError("Missing known-good test values (at least two)")
    if not msg['bad']:
        raise click.UsageError("Missing known-bad test values")

    res = await obj.client._request(
        action="set_internal",
        value=msg,
        path=("type",) + path,
        iter=False,
        nchain=3 if obj.meta else 0,
        **({"chain":chain} if chain else {})
    )
    if obj.meta:
        yprint(res)


@cli.command()
@click.option(
    "-R",
    "--raw",
    is_flag=True,
    help="Print just the path."
)
@click.option(
    "-t", "--type", multiple=True, help="Type to link to. Multiple for subytpes."
)
@click.option("-d", "--delete", help="Use to delete this mapping.")
@click.argument("path", nargs=-1)
@click.pass_obj
async def match(obj, path, type, delete, raw):
    """Match a type to a path (read, if no type given)"""
    if not path:
        raise click.UsageError("You need a non-empty path.")
    if type and delete:
        raise click.UsageError("You can't both set and delete a path.")
    if raw and (type or delete):
        raise click.UsageError("You can only print the raw path when reading a match.")

    if delete:
        res = await obj.client._request(action="delete_internal", path=("type",) + path)
        if obj.meta:
            yprint(res)
        return

    msg = {}
    if type:
        msg['type'] = type
        act = "set_internal"
    elif delete:
        act = "delete_internal"
    else:
        act = "get_internal"
    res = await obj.client._request(
        action=act,
        value=msg,
        path=("match",) + path,
        iter=False,
        nchain=3 if obj.meta else 0,
    )
    if obj.meta:
        yprint(res)
    elif type or delete:
        pass
    else:
        print(" ".join(str(x) for x in res.type))


