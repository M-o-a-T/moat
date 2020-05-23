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
@click.pass_obj
async def cli(obj):
    """
    Manage Home Assistant integration.
    """
    pass


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
      dynamically-configured entries. The default is 'home' 'ass' 'dyn'.

    This command can only be used once.
    """
    res = await obj.client.get(".hass")
    if res.get('value',NotGiven) is not NotGiven:
        if init or conv or data:
            raise click.UsageError("You already used this command.")


        return
    elif not init:
        raise click.UsageError("You need to use the 'init' option to do this.")
    if not conv:
        conv="hassco"
    if not path:
        path="home ass dyn".split()
    await obj.client.set(".hass", value=dict(conv=conv,path=path))
    print("Setup stored.")
    await setup_conv(obj)

@cli.command()
@click.pass_obj
async def conv(obj):
    """Update stored converters."""
    await setup_conv(obj)
    print("Done.")


async def setup_conv(obj):
    """
    Set up converters.
    """
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

    print("Done.")



