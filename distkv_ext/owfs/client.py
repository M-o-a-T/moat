# command line interface

import sys
import asyncclick as click
from functools import partial
from distkv.exceptions import ClientError
from distkv.util import yprint, attrdict, combine_dict, data_get, NotGiven

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
        if path[1] == '*':
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
                    c = '*'
                else:
                    f = "%02x" % (r.path[-2],)
                    c = "%012x" % (r.path[-1],)
                rr = res.setdefault(f,{})
                if not obj.meta:
                    r = r.value
                rr[c] = r
            else:
                if len(r.path) == 0:
                    c = '*'
                else:
                    c = "%012x" % (r.path[-1],)
                if not obj.meta:
                    r = r.value
                res[c] = r

    yprint(res)


@cli.command()
@click.option("-d","--device",help="Device to modify.")
@click.option("-f","--family",help="Device family to modify.")
@click.argument("attribute", nargs=1)
@click.argument("interval", nargs=1)
@click.pass_obj
async def poll(obj,device,family,attribute,interval):
    """Set poll interval for some attribute.
    """
    if (device is not None)+(family is not None) != 1:
        raise click.UsageError("Either family or device code must be given")

    if family:
        fd = (int(family,16),)
    else:
        f,d = device.split('.',2)[0:2]
        fd = (int(f,16), int(d,16))
    if interval == '-':
        interval = None
    else:
        interval = float(interval)
        if interval <= 0.1:
            raise click.UsageError("The interval must be at least 0.1 sec")

    res = await obj.client.get(*obj.cfg.owfs.prefix, *fd, nchain=3)

    val = res.get('value',{})
    pol = val.setdefault('poll',{})
    if interval is None:
        pol.pop(attribute,None)
    else:
        pol[attribute] = interval
    res = await obj.client.set(*obj.cfg.owfs.prefix, *fd, chain=res.get('chain',None), value=val)
    if obj.meta:
        yprint(res)


@cli.command()
@click.option("-d","--device",help="Device to modify.")
@click.option("-f","--family",help="Device family to modify.")
@click.option("-v","--value", help="The attribute to set or delete")
@click.option("-e","--eval", "eval_", is_flag=True, help="Whether to eval the value")
@click.argument("name", nargs=-1)
@click.pass_obj
async def set(obj,device,family, value,eval_,name):
    """Set some random attribute.
    """
    if (device is not None)+(family is not None) != 1:
        raise click.UsageError("Either family or device code must be given")

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

    if not len(name):
        raise click.UsageError("You need to name the attribute")
    name = list(name)
    res = await obj.client.get(*obj.cfg.owfs.prefix, *fd, nchain=3)

    val = res.get('value',{})
    pol = val
    for n in name[:-1]:
        pol = pol.setdefault(n,{})
    if value is NotGiven:
        while name:
            pol.pop(name.pop(), None)
            if pol:
                break
            pol = val
            for n in name[:-1]:
                pol = pol[n]
    else:
        pol[name[-1]] = value
    res = await obj.client.set(*obj.cfg.owfs.prefix, *fd, chain=res.get('chain',None), value=val)
    if obj.meta:
        yprint(res)


@cli.command()
@click.pass_obj
async def monitor(obj):
    """Stand-alone task to monitor OWFS.
    """
    from distkv_ext.owfs.task import task
    await task(obj.client, obj.cfg)
    
