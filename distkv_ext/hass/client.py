# command line interface

import os
import sys
import asyncclick as click
import yaml
from functools import partial
from collections.abc import Mapping

from distkv.exceptions import ClientError
from distkv.util import yprint, attrdict, combine_dict, data_get, NotGiven, path_eval
from distkv.util import res_delete, res_get, res_update

import logging

logger = logging.getLogger(__name__)

@main.group(short_help="Manage Home Assistant.")  # pylint: disable=undefined-variable
@click.option("-t", "--test", is_flag=True, help="Use test data.")
@click.pass_obj
async def cli(obj,test):
    """
    Manage Home Assistant integration.
    """
    obj.hass_test = test
    obj.hass_name = (".hass","test") if test else (".hass",)
    res = await obj.client.get(*obj.hass_name)
    if res.get('value',NotGiven) is not NotGiven:
        obj.hass = attrdict(**res.value)



@cli.command()
@click.option("-i", "--init", is_flag=True, help="Actually set the data.")
@click.option("-c", "--conv", help="The converter to use for HASS.")
@click.argument("path", nargs=-1)
@click.pass_obj
async def init(obj, conv, path, init):
    """Set up stored data and paths for Home Assistant.

    Arguments:
    - The converter that uses the data conversion entries.
      The default is 'hassco'.
    - the path to the HASS subtree in DistKV which contains your
      dynamically-configured entries. The default is 'home' 'ass' 'cfg',
      or 'test' 'retain' 'cfg' when testing.

    The path's last word is the "discovery_prefix" in Home Assistant's
    MQTT configuration. It cannot contain a slash.

    With '-i', this command saves the data; it can only be used once.
    Otherwise the current settings will be listed.
    """
    res = await obj.client.get(*obj.hass_name)
    if res.get('value',NotGiven) is not NotGiven:
        if init or conv or path:
            raise click.UsageError("You already used this command.")
        yprint(res.value, stream=obj.stdout)
        return
    elif not init:
        raise click.UsageError("You need to use the 'init' option to do this.")
    if not conv:
        conv="hassco"
    if not path:
        if obj.hass_test:
            path="test retain cfg".split()
        else:
            path="home ass cfg".split()
    await obj.client.set(*obj.hass_name, value=dict(conv=conv,path=path))
    print("Setup stored.")
    await setup_conv(obj)

@cli.command()
@click.pass_obj
async def conv(obj):
    """Update stored converters."""
    chg = await setup_conv(obj)
    if not chg:
        print("No changes.")


async def setup_conv(obj):
    """
    Set up converters.
    """
    n=0

    r = await obj.client.get(".hass")
    conv = r.value['conv']
    path = r.value['path']

    def construct_yaml_tuple(self, node):
        seq = self.construct_sequence(node)
        return tuple(seq)

    # This is a hack, FIXME
    from yaml.constructor import SafeConstructor
    SafeConstructor.add_constructor(
        u'tag:yaml.org,2002:seq',
        construct_yaml_tuple)

    with open(os.path.join(os.path.dirname(__file__) ,"schema.yaml")) as f:
        cfg = yaml.safe_load(f)
    for k,v in cfg['codec'].items():
        k=k.split(" ")
        r = await obj.client._request(action="get_internal",path=["codec"]+k)
        if r.get('value',{}) != v:
            print("codec",*k)
            await obj.client._request(action="set_internal",path=["codec"]+k, value=v)
            n += 1

    ppa = ("conv",conv)+path
    for k,v in cfg['conv'].items():
        for kk,vv in v.items():
            vv=dict(codec=vv)
            for ap in ('+',),('+','+'):
                p = ppa+(k,)+ap+(kk,)
                r = await obj.client._request(action="get_internal",path=p)
                if r.get('value',{}) != vv:
                    print(*p)
                    await obj.client._request(action="set_internal",path=p, value=vv)
                    n += 1
    return n


class _S:
    def __init__(self,*k):
        self._d = set()
        for v in k:
            self._d.add(v)

    def __getattr__(self,x):
        if x[0] == '_':
            return super().__getattr__(x)
        return x in self._d

_types = {
        "light": attrdict(
            cmd=(str,"‹prefix›/light/‹path›/cmd","topic for commands","command_topic"),
            state=(str,"‹prefix›/light/‹path›/state","topic for state","state_topic"),
            bright=(bool,False,"Brightness control?","brightness"),
            bright_cmd=(str,"‹prefix›/light/‹path›/brightness/state","brightness control","brightness_command_topic"),
            bright_state=(str,"‹prefix›/light/‹path›/brightness/cmd","brightness state","brightness_state_topic"),
            _payload=True,
            ),
        "binary_switch":attrdict(
            cmd=(str,"‹prefix›/binary_switch/‹path›/cmd","topic for commands","command_topic"),
            state=(str,"‹prefix›/binary_switch/‹path›/state","topic for state","state_topic"),
            _payload=True,
            ),
        }

for _v in _types.values():
    if _v.pop('_payload',False):
        _v.on=(str,"on","payload to turn on","payload_on")
        _v.off=(str,"off","payload to turn off","payload_off")
    _v.name=(str,"‹type› ‹path›","The name of this device","name")
    _v.uid=(str,"dkv_‹tock›","A unique ID for this device","unique_id")

@cli.command()
@click.pass_obj
@click.option("-d","--delete",is_flag=True,help="delete this entry?")
@click.option("-o","--option",multiple=True,help="Special entry (string)")
@click.option("-O","--eval-option",multiple=True,help="Special entry (evaluated)")
@click.option("-L","--list-options",is_flag=True,help="List possible options")
@click.argument("typ", nargs=1)
@click.argument("path", nargs=-1)
async def set(obj,typ,path,delete,option,eval_option,list_options):
    """
    Add or modify a device.

    Boolean states can be set with "-o NAME" and cleared with "-o -name".
    Known types: %s
    """%(" ".join(_types.keys()),)
    try:
        t = _types[typ]
    except KeyError:
        raise click.UsageError("I don't know this type.")
    if list_options or delete:
        if option or eval_option or (list_options and delete):
            raise click.UsageError("Deletion and options at the same time? No.")

    if list_options:
        lm=[0,0,0,0]
        for k,v in t.items():
            lm[0]=max(lm[0],len(k))
            lm[1]=max(lm[1],len(v[0].__name__))
            lm[2]=max(lm[2],len(str(v[1])))
            lm[3]=max(lm[3],len(v[2]))
        fmt=" ".join("%-"+str(x)+"s" for x in lm)
            
        for k,v in t.items():
            print(fmt % (k,v[0].__name__,v[1],v[2]))
        return

    if len(path) not in (1,2):
        raise click.UsageError("The path must consist of 1 or 2 words.")
    cp = obj.hass.path+(typ,)+path+("config",)

    res = await obj.client.get(*cp, nchain=2)
    r=attrdict()
    if res.get('value',NotGiven) is NotGiven:
        val = attrdict()
        r.chain = None
    else:
        val = attrdict(**res.value)
        r.chain = res.chain
    if delete:
        await obj.client.delete(*cp, **r)
        return

    i=attrdict()
    for k in option:
        if k[0] in '-!':
            k =k[1:]
            v = False
        elif '=' in k:
            k,v = k.split("=",1)
        else:
            v = True
        i[t[k][3]] = v
    for k in eval_option:
        k,v=k.split("=",1)
        i[t[k][3]] = eval(v)
    if "unique_id" in i and "unique_id" in val:
        raise click.UsageError("A unique ID is fixed. You can't change it.")

    d=attrdict()
    for k,v in t.items():
        if k == "unique":
            continue
        if k == "name":
            vv = "_".join(path)
        elif k == "cmd":
            vv = "/".join((obj.hass.path[-1],typ,*path,"cmd"))
        elif k.endswith("_cmd"):
            vv = "/".join((obj.hass.path[-1],typ,*path,k[:-4],"cmd"))
        elif k == "state":
            vv = "/".join((obj.hass.path[-1],typ,*path,"state"))
        elif k.endswith("_state"):
            vv = "/".join((obj.hass.path[-1],typ,*path,k[:-6],"state"))
        else:
            vv = v[1]
        try:
            kk,_ = k.split('_')
        except ValueError:
            pass
        else:
            kk = t[kk][3]
            if not (i[kk] if kk in i else val.get(kk,False)):
                continue
        d[v[3]] = vv
        if v[3] in i:
            if not isinstance(i[v[3]],v[0]):
                raise click.UsageError("Option %r is not a %s" % (k,v[0].__name__))

    v=combine_dict(i,val,d)
    if "unique" in t and "unique_id" not in v:
        tock = await obj.client.get_tock()
        v['unique_id'] = "dkv_"+str(tock)

    await obj.client.set(*cp, value=v, **r)


@cli.command()
@click.pass_obj
@click.argument("typ", nargs=1)
@click.argument("path", nargs=-1)
async def get(obj,typ,path):
    """
    Display a device's config.

    Known types: %s
    """%(" ".join(_types.keys()),)
    try:
        t = _types[typ]
    except KeyError:
        raise click.UsageError("I don't know this type.")

    cp = obj.hass.path+(typ,)+path
    if not len(path):
        async for r in obj.client.get_tree(*cp):
            if r.path[-1] != 'config':
                continue
            print(r.value.name, typ," ".join(r.path[:-1]))
        return

    res = await obj.client.get(*cp, "config", nchain=2)
    if res.get('value',NotGiven) is NotGiven:
        print("Not found.")
        return
    yprint(res.value, stream=obj.stdout)

@cli.command()
@click.pass_obj
@click.argument("typ", nargs=1)
@click.argument("path", nargs=-1)
async def delete(obj,typ,path):
    """
    Delete a device.

    Known types: %s
    """%(" ".join(_types.keys()),)
    try:
        t = _types[typ]
    except KeyError:
        raise click.UsageError("I don't know this type.")

    cp = obj.hass.path+(typ,)+path

    res = await obj.client.get(*cp, "config", nchain=2)
    r=attrdict()
    if res.get('value',NotGiven) is NotGiven:
        print("Not found.")
        return
    v = attrdict(**res.value)
    r.chain = res.chain
    await obj.client.delete(*cp, "config",**r)
    await obj.client.delete(*cp, "state")
    await obj.client.delete(*cp, "cmd")

