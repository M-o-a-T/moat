# command line interface

import os
import asyncclick as click

from moat.util import yprint, attrdict, combine_dict, NotGiven, P, Path, yload

import logging

logger = logging.getLogger(__name__)


@click.group(short_help="Manage Home Assistant.")
@click.option("-t", "--test", is_flag=True, help="Use test data.")
@click.pass_obj
async def cli(obj, test):
    """
    Manage Home Assistant integration.
    """
    obj.hass_test = test
    if test:
        obj.hass_name = Path("test","retain")
    else:
        obj.hass_name = Path("home","ass","dyn")


@cli.command("conv")
@click.option("-u", "--user", help="The user name used for HASS.", default="hassco")
@click.pass_obj
async def conv_(obj, user):
    """Update stored converters."""
    chg = await setup_conv(obj, user)
    if not chg:
        print("No changes.")


async def setup_conv(obj, user):
    """
    Set up converters.
    """
    n = 0

    with open(os.path.join(os.path.dirname(__file__), "schema.yaml")) as f:
        cfg =  yload(f)
    for k, v in cfg["codec"].items():
        k = k.split(" ")
        r = await obj.client._request(action="get_internal", path=["codec"] + k)
        if r.get("value", {}) != v:
            print("codec", *k)
            await obj.client._request(action="set_internal", path=["codec"] + k, value=v)
            n += 1

    ppa = Path("conv", user) + obj.hass_name
    for k, v in cfg["conv"].items():
        for kk, vv in v.items():
            vv = dict(codec=vv)
            if k == "+":
                p = (*ppa, "#", *kk.split("/"))
            else:
                p = (*ppa, k, "#", *kk.split("/"))
            r = await obj.client._request(action="get_internal", path=p)
            if r.get("value", {}) != vv:
                print(*p)
                await obj.client._request(action="set_internal", path=p, value=vv)
                n += 1
    return n


class _S:
    def __init__(self, *k):
        self._d = set()
        for v in k:
            self._d.add(v)

    def __getattr__(self, x):
        if x[0] == "_":
            return super().__getattribute__(x)
        return x in self._d


_types = {
    "light": attrdict(
        cmd=(str, "‹prefix›/light/‹path›/cmd", "topic for commands", "command_topic"),
        state=(str, "‹prefix›/light/‹path›/state", "topic for state", "state_topic"),
        _payload=True,
    ),
    "switch": attrdict(
        cmd=(str, "‹prefix›/binary_switch/‹path›/cmd", "topic for commands", "command_topic"),
        state=(str, "‹prefix›/binary_switch/‹path›/state", "topic for state", "state_topic"),
        icon=(str, None, "Device icon", "icon"),
        _payload=True,
        _payloads=True,
    ),
    "binary_sensor": attrdict(
        state=(str, "‹prefix›/binary_switch/‹path›/state", "topic for state", "state_topic"),
        unit=(str, None, "Unit of measurement", "unit_of_measurement"),
        icon=(str, None, "Device icon", "icon"),
        _payload=True,
    ),
    "sensor": attrdict(
        state=(str, "‹prefix›/binary_switch/‹path›/state", "topic for state", "state_topic"),
        unit=(str, None, "Unit of measurement", "unit_of_measurement"),
        cls=(str, None, "Device class", "device_class"),
        icon=(str, None, "Device icon", "icon"),
    ),
    "lock": attrdict(
        cmd=(str, "‹prefix›/lock/‹path›/cmd", "topic for commands", "command_topic"),
        state=(str, "‹prefix›/lock/‹path›/state", "topic for state", "state_topic"),
        on=(str, "on", "payload to lock", "payload_lock"),
        off=(str, "off", "payload to unlock", "payload_unlock"),
        ons=(str, "on", "state for locked", "state_locked"),
        offs=(str, "off", "state for unlocked", "state_unlocked"),
    ),
}
_types_plus = {
    "light": dict(
        bright=dict(
            brightcmd=(
                str,
                "‹prefix›/light/‹path›/brightness/state",
                "brightness control",
                "brightness_command_topic",
            ),
            brightstate=(
                str,
                "‹prefix›/light/‹path›/brightness/cmd",
                "brightness state",
                "brightness_state_topic",
            ),
            brightscale=(int, 100, "brightness state", "brightness_scale"),
            cmdtype=(str, "brightness", "Command type: brightness/first/last", "on_command_type"),
        ),
    ),
}

for _v in _types.values():
    if _v.pop("_payload", False):
        _v.on = (str, "on", "payload to turn on", "payload_on")
        _v.off = (str, "off", "payload to turn off", "payload_off")
    if _v.pop("_payloads", False):
        _v.ons = (str, "on", "state when turned on", "state_on")
        _v.offs = (str, "off", "state when turned off", "state_off")
    _v.name = (str, "‹type› ‹path›", "The name of this device", "name")
    _v.uid = (str, "dkv_‹tock›", "A unique ID for this device", "unique_id")
    _v.device = (str, "", "ID of the device this is part of", "device")


@cli.command(
    "set",
    help="""Add or modify a device.

Boolean states can be set with "-o NAME" and cleared with "-o -name".
Others can be set with "-o NAME=VALUE" (string), "-O NAME=VALUE" (evaluated),
or "-O NAME=.VALUE" (split by dots or slashes).

Known types: %s
"""
    % (" ".join(_types.keys()),),
)
@click.pass_obj
@click.option("-o", "--option", multiple=True, help="Special entry (string)")
@click.option("-O", "--eval-option", multiple=True, help="Special entry (evaluated)")
@click.option("-L", "--list-options", is_flag=True, help="List possible options")
@click.option("-p", "--plus", multiple=True, help="Add a sub-option")
@click.option(
    "-f", "--force", is_flag=True, help="Override some restrictions. Use with extreme caution."
)
@click.argument("typ", nargs=1)
@click.argument("path", nargs=1)
async def set_(obj, typ, path, option, eval_option, list_options, force, plus):
    path = P(path)
    if typ == "-":
        t = None
    else:
        try:
            t = _types[typ].copy()
            tp = _types_plus.get(typ, {})
        except KeyError:
            raise click.UsageError("I don't know this type.")
        for p in plus:
            try:
                p = tp[p]
            except KeyError:
                raise click.UsageError("There are no options for '%s'.")
            else:
                t.update(p)

    if list_options:
        if option or eval_option:
            raise click.UsageError("Deletion and options at the same time? No.")

        if t is None:
            for k in _types.keys():
                print(k, file=obj.stdout)
        else:
            lm = [0, 0, 0, 0]

            for k, v in t.items():
                lm[0] = max(lm[0], len(k))
                lm[1] = max(lm[1], len(v[0].__name__))
                lm[2] = max(lm[2], len(str(v[1])))
                lm[3] = max(lm[3], len(v[2]))
            fmt = " ".join("%-" + str(x) + "s" for x in lm)

            for k, v in t.items():
                print(fmt % (k, v[0].__name__, v[1], v[2]), file=obj.stdout)
            if tp:
                print("Plus", " ".join(tp.keys()))
        return

    if len(path) not in (1, 2):
        raise click.UsageError("The path must consist of 1 or 2 words.")
    cp = obj.hass_name + (typ, *path, "config")

    res = await obj.client.get(cp, nchain=2)
    r = attrdict()
    if res.get("value", NotGiven) is NotGiven:
        val = attrdict()
        r.chain = None
    else:
        val = attrdict(**res.value)
        r.chain = res.chain

    i = attrdict()
    for k in option:
        if k[0] in "-!":
            k = k[1:]
            v = False
            if t[k][1] is not bool:
                val.pop(k, None)
                continue
        elif "=" in k:
            k, v = k.split("=", 1)
        else:
            v = True
        i[t[k][3]] = v
    for k in eval_option:
        k, v = k.split("=", 1)
        if v[0] in "/.":
            i[t[k][3]] = v[1:].split(v[0])
        else:
            i[t[k][3]] = eval(v)  # pylint: disable=eval-used
    if "unique_id" in i and "unique_id" in val and not force:
        raise click.UsageError("A unique ID is fixed. You can't change it.")

    d = attrdict()
    for k, v in t.items():
        if k == "uid":
            continue
        elif isinstance(v, dict):
            continue  # plus option
        elif k == "name":
            vv = "_".join(path)
        elif k == "cmd":
            vv = "/".join((*obj.hass_name, typ, *path, "cmd"))
        elif k.endswith("cmd"):
            vv = "/".join((*obj.hass_name, typ, *path, k[:-3], "cmd"))
        elif k == "state":
            vv = "/".join((*obj.hass_name, typ, *path, "state"))
        elif k.endswith("state"):
            vv = "/".join((*obj.hass_name, typ, *path, k[:-5], "state"))
        elif v[1] == 0 or v[1] == "":
            continue
        else:
            vv = v[1]
        try:
            kk, _ = k.split("_")
        except ValueError:
            pass
        else:
            kk = t[kk][3]
            if not (i[kk] if kk in i else val.get(kk, False)):
                continue
        d[v[3]] = vv
        if v[3] in i:
            if not isinstance(i[v[3]], v[0]):
                raise click.UsageError("Option %r is not a %s" % (k, v[0].__name__))

    v = combine_dict(i, val, d)
    v = {k: v for k, v in v.items() if v is not None}
    if "uid" in t and "unique_id" not in v:
        tock = await obj.client.get_tock()
        v["unique_id"] = "dkv_" + str(tock)
    if "device_class" in v:
        if v["device_class"] not in (
            None,
            "battery",
            "humidity",
            "illuninance",
            "signal_strength",
            "temperature",
            "power",
            "pressure",
            "timestamp",
        ):
            raise click.UsageError("Device class %r is unknown" % (v["device_class"],))
    if "device" in v:
        dv = v["device"]
        if not dv:
            del v["device"]
        elif isinstance(dv, str):
            v["device"] = dict(identifiers=dv.split(":"))
    if "cmd" in t:
        v["retain"] = True
    else:
        v.pop("retain", None)

    await obj.client.set(cp, value=v, **r)


set_.__doc__ = """
    Add or modify a device.

    Boolean states can be set with "-o NAME" and cleared with "-o -name".
    Known types: %s
    """ % (
    " ".join(_types.keys()),
)


@cli.command(help="Display a device, list devices")
@click.pass_obj
@click.option("-c", "--cmd", is_flag=True, help="Use command-line names")
@click.argument("typ", nargs=1)
@click.argument("path", nargs=1)
async def get(obj, typ, path, cmd):
    path = P(path)
    if typ == "-":
        res = await obj.client._request(action="enumerate", path=obj.hass_name, empty=True)
        for r in res.result:
            print(r, file=obj.stdout)
        return
    try:
        t = _types[typ]
    except KeyError:
        raise click.UsageError("I don't know this type.")

    if cmd:
        tt = {}
        for k, v in t.items():
            tt[v[3]] = k
        cmd = lambda x: tt.get(x, x)
    else:
        cmd = lambda x: x
    cp = obj.hass_name + (typ,) + path
    if not len(path):
        async for r in obj.client.get_tree(cp):
            if r.path[-1] != "config":
                continue
            print(r.value.name, typ, r.path[:-1])
        return

    res = await obj.client.get(cp|"config", nchain=2)
    if res.get("value", NotGiven) is NotGiven:
        print("Not found.")
        return
    val = res.value
    for k, v in val.items():
        print(cmd(k), v, file=obj.stdout)


get.__doc__ = """
    Display a device's configuration.

    Known types: %s
    """ % (
    " ".join(_types.keys()),
)


@cli.command(help="Delete a device")
@click.pass_obj
@click.argument("typ", nargs=1)
@click.argument("path", nargs=1)
async def delete(obj, typ, path):
    """Delete a device.
    """

    path = P(path)
    if typ not in _types:
        raise click.UsageError("I don't know this type.")

    cp = obj.hass_name + (typ, *path)

    res = await obj.client.get(cp|"config", nchain=2)
    if res.get("value", NotGiven) is NotGiven:
        print("Not found.")
        return
    await obj.client.delete_tree(cp)
