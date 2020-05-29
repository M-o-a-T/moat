# command line interface

import sys
import asyncclick as click
from functools import partial
from distkv.exceptions import ClientError
from distkv.util import yprint, attrdict, combine_dict, data_get, NotGiven
from distkv.util import res_delete, res_get, res_update

import logging

logger = logging.getLogger(__name__)

@main.group(short_help="Manage 1wire devices.")  # pylint: disable=undefined-variable
@click.pass_obj
async def cli(obj):
    """
    List Onewire devices, modify device handling …
    """
    pass


@cli.command("list")
@click.argument("path", nargs=-1)
@click.pass_obj
async def list_(obj, path):
    """Emit the current state as a YAML file.
    """
    res = {}
    if len(path) > 2:
        raise click.UsageError("Only one or two path elements allowed")
    if len(path) == 2:
        if path[1] == '-':
            path = path[:-1]
        path = [int(x,16) for x in path]
        res = await obj.client.get(*obj.cfg.owfs.prefix, *path, nchain=obj.meta)
        if not obj.meta:
            res = res.value

    else:
        path = [int(x,16) for x in path]
        async for r in obj.client.get_tree(*obj.cfg.owfs.prefix, *path, nchain=obj.meta, min_depth=max(0,1-len(path)),max_depth=2-len(path)):

            if len(path) == 0:
                if len(r.path) == 1:
                    f = "%02x" % (r.path[-1],)
                    c = '_'
                else:
                    f = "%02x" % (r.path[-2],)
                    c = "%012x" % (r.path[-1],)
                rr = res.setdefault(f,{})
                if not obj.meta:
                    r = r.value
                rr[c] = r
            else:
                if len(r.path) == 0:
                    c = '_'
                else:
                    c = "%012x" % (r.path[-1],)
                if not obj.meta:
                    r = r.value
                res[c] = r

    yprint(res, stream=obj.stdout)


@cli.command('attr')
@click.option("-d","--device",help="Device to modify.")
@click.option("-f","--family",help="Device family to modify.")
@click.option("-i","--interval",type=float,help="read value every N seconds")
@click.option("-w","--write",is_flag=True,help="Modify write access")
@click.argument("attr", nargs=1)
@click.argument("path", nargs=-1)
@click.pass_obj
async def attr_(obj,device,family,write,attr,interval,path):
    """Add data to repeatedly read an 1wire device's attribute.

    Family codes cannot yet have a path.
    A path of '-' deletes the entry.
    If you set neither interval nor path, reports the current
    values.
    """
    if (device is not None)+(family is not None) != 1:
        raise click.UsageError("Either family or device code must be given")
    if interval and write:
        raise click.UsageError("Writing isn't polled")

    remove = False
    if len(path) == 1 and path[0] == '-':
        path = ()
        remove = True

    if family:
        if path:
            raise click.UsageError("You cannot set a per-family path")
        fd = (int(family,16),)
    else:
        f,d = device.split('.',2)[0:2]
        fd = (int(f,16), int(d,16))

    res = await obj.client.get(*obj.cfg.owfs.prefix, *fd, nchain=3)
    val = res.get('value',{})
    v = val.setdefault('attr',{})
    if remove:
        del v[attr]
    else:
        v = v.setdefault(attr,{})
        if path:
            v['src' if write else 'dest'] = path
        if interval:
            v['interval'] = interval
        if not v:
            yprint(v, stream=obj.stdout)
            return

    res = await obj.client.set(*obj.cfg.owfs.prefix, *fd, chain=res.get('chain',None), value=val)
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.option("-d","--device",help="Device to modify.")
@click.option("-f","--family",help="Device family to modify.")
@click.option("-v","--value", help="The attribute to set or delete")
@click.option("-e","--eval", "eval_", is_flag=True, help="Whether to eval the value")
@click.argument("name", nargs=-1)
@click.pass_obj
async def set(obj,device,family, value,eval_,name):
    """Set or delete some random attribute.

    For deletion, use the options '-ev-'.

    You cannot replace a dict element with a non-dict or vice versa.
    Delete it first.
    """
    if (device is not None)+(family is not None) != 1:
        raise click.UsageError("Either family or device code must be given")
    if not len(name):
        raise click.UsageError("You need to name the attribute")

    if family:
        fd = (int(family,16),)
    else:
        f,d = device.split('.',2)[0:2]
        fd = (int(f,16), int(d,16))

    if eval_:
        if value == "-":
            value = NotGiven
        else:
            value = eval(value)

    name = list(name)
    res = await obj.client.get(*obj.cfg.owfs.prefix, *fd, nchain=3)
    if value is NotGiven:
        val = res_delete(res, *name)
    else:
        val = res_update(res, *name, value=value)
    res = await obj.client.set(*obj.cfg.owfs.prefix, *fd, chain=res.get('chain',None), value=val)
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.pass_obj
async def monitor(obj):
    """Stand-alone task to monitor OWFS.
    """
    from distkv_ext.owfs.task import task
    await task(obj.client, obj.cfg)

