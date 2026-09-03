"""
Command-line interface for moat.link.ha.

Manages Home-Assistant MQTT-discovery configuration stored in the
MoaT-Link data tree.  Device definitions live under the configured
``link.ha.prefix``.
"""

from __future__ import annotations

import logging

import asyncclick as click

from moat.util import (
    NotGiven,
    attrdict,
    combine_dict,
)
from moat.lib.path import (
    P,
    Path,
)
from moat.lib.run import AliasedGroup, attr_args, process_args
from moat.link.client import Link

logger = logging.getLogger(__name__)

_DEV_CLS = {
    None,
    "apparent_power",
    "aqi",
    "atmospheric_pressure",
    "battery",
    "carbon_dioxide",
    "carbon_monoxide",
    "current",
    "data_rate",
    "data_size",
    "distance",
    "energy",
    "energy_storage",
    "frequency",
    "gas",
    "humidity",
    "illuninance",
    "irradiance",
    "moisture",
    "monetary",
    "nitrogen_dioxide",
    "nitrogen_monoxide",
    "nitrous_oxide",
    "ozone",
    "ph",
    "pm1",
    "pm10",
    "pm25",
    "power",
    "power_factor",
    "precipitation",
    "precipitation_intensity",
    "pressure",
    "reactive_power",
    "signal_strength",
    "sound_pressure",
    "speed",
    "sulphur_dioxide",
    "temperature",
    "volatile_organic_compounds",
    "voltage",
    "volume",
    "volume_storage",
    "water",
    "weight",
    "wind_speed",
}


_types = {
    "light": attrdict(
        cmd=(str, "‹prefix›/light/‹path›/cmd", "topic for commands", "command_topic"),
        state=(str, "‹prefix›/light/‹path›/state", "topic for state", "state_topic"),
        _payload=True,
    ),
    "switch": attrdict(
        cmd=(
            str,
            "‹prefix›/binary_switch/‹path›/cmd",
            "topic for commands",
            "command_topic",
        ),
        state=(
            str,
            "‹prefix›/binary_switch/‹path›/state",
            "topic for state",
            "state_topic",
        ),
        icon=(str, None, "Device icon", "icon"),
        _payload=True,
        _payloads=True,
    ),
    "binary_sensor": attrdict(
        state=(
            str,
            "‹prefix›/binary_sensor/‹path›/state",
            "topic for state",
            "state_topic",
        ),
        unit=(str, None, "Unit of measurement", "unit_of_measurement"),
        icon=(str, None, "Device icon", "icon"),
        _payload=True,
    ),
    "number": attrdict(
        cmd=(
            str,
            "‹prefix›/number/‹path›/cmd",
            "topic for writing the value (r/w)",
            "command_topic",
        ),
        state=(
            str,
            "‹prefix›/number/‹path›/state",
            "topic for reading a value update",
            "state_topic",
        ),
        unit=(str, None, "Unit of measurement", "unit_of_measurement"),
        step=(float, None, "Step", "step"),
        cls=(str, None, "Device class", "device_class"),
        icon=(str, None, "Device icon", "icon"),
        min=(float, None, "minimum value", "min"),
        max=(float, None, "maximum value", "max"),
    ),
    "sensor": attrdict(
        state=(str, "‹prefix›/sensor/‹path›/state", "topic for state", "state_topic"),
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
            cmdtype=(
                str,
                "brightness",
                "Command type: brightness/first/last",
                "on_command_type",
            ),
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
    _v.uid = (str, None, "A unique ID for this device", "unique_id")
    _v.device = (str, "", "ID of the device this is part of", "device")
    _v.template = (str, None, "template for display", "value_template")


@click.group(cls=AliasedGroup, short_help="Manage Home Assistant.")
@click.option("-t", "--test", is_flag=True, help="Use test data.")
@click.pass_context
async def cli(ctx, test):
    """
    Manage Home Assistant integration.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(
        Link(cfg, common=True, only=getattr(obj, "link_name", None))
    )
    obj.hass_test = test
    ha_cfg = obj.cfg.link.ha
    if test:
        obj.hass_name = Path.build(("test", "retain"))
    else:
        obj.hass_name = ha_cfg.prefix
    obj.ha_cfg = ha_cfg


@cli.command(
    "set",
    help="""Add or modify a device.

Known types: {}
""".format(" ".join(_types.keys())),
)
@click.pass_obj
@attr_args
@click.option("-L", "--list-options", is_flag=True, help="List possible options")
@click.option("-a", "--plus", multiple=True, help="Add a sub-option")
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Override some restrictions. Use with extreme caution.",
)
@click.argument("typ", nargs=1)
@click.argument("path", nargs=1)
async def set_(obj, typ, path, list_options, force, plus, **kw):
    path = P(path)
    if typ == "-":
        t = None
        tp = {}
    else:
        try:
            t = _types[typ].copy()
            tp = _types_plus.get(typ, {})
        except KeyError:
            raise click.UsageError("I don't know this type.") from None
        for p in plus:
            try:
                p = tp[p]  # noqa: PLW2901
            except KeyError:
                raise click.UsageError("There are no options for '%s'.") from None
            else:
                t.update(p)

    if list_options:
        if any(kw.values()):
            raise click.UsageError("Deletion and options at the same time? No.")

        if t is None:
            for k in _types:
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

    if t is None:
        raise click.UsageError("Type '-' is only valid with --list-options.")

    if len(path) not in (1, 2):
        raise click.UsageError("The path must consist of 1 or 2 words.")
    cp = obj.hass_name / typ + path / "config"

    try:
        res = await obj.conn.d_get(cp)
    except KeyError:
        val = attrdict()
    else:
        if res is NotGiven:
            val = attrdict()
        else:
            val = attrdict(**res)

    i = process_args(attrdict(), **kw)

    d = {v[3]: v[1] for v in t.values() if v[1] is not None}
    for k, v in t.items():
        if k == "name":
            vv = "_".join(path)
        elif k == "cmd":
            vv = "/".join((*obj.hass_name, typ, *path, "cmd"))
        elif k.endswith("cmd"):
            vv = "/".join((*obj.hass_name, typ, *path, k[:-3], "cmd"))
        elif k == "state":
            vv = "/".join((*obj.hass_name, typ, *path, "state"))
        elif k.endswith("state"):
            vv = "/".join((*obj.hass_name, typ, *path, k[:-5], "state"))
        else:
            continue
        d[v[3]] = vv

    for k, v in i.items():
        tt = t.get(k)
        if k == "uid":
            if "unique_id" in val and i.uid != val.unique_id and not force:
                raise click.UsageError("A unique ID is fixed. You can't change it.")
        elif isinstance(v, dict):
            continue  # plus option
        elif not force and k not in t:
            logger.warning("Key %r may be unknown. Skipping.", k)
            continue
        vv = i[k]
        if tt is not None:
            if tt[0] is float and isinstance(vv, int):
                pass
            elif not isinstance(vv, tt[0]):
                raise click.UsageError(f"Option {k!r} is {vv!r}, not a {tt[0].__name__}")
        val[k if tt is None else tt[3]] = vv

    v = combine_dict(val, d)
    v = {k: v for k, v in v.items() if v is not None}
    if "unique_id" not in v:
        import uuid  # noqa: PLC0415

        tock = uuid.uuid4().hex[:13]
        v["unique_id"] = f"dmoat_{tock}"
    if v.get("device_class") not in _DEV_CLS:
        raise click.UsageError("Device class {!r} is unknown".format(v["device_class"]))
    if "device" in v:
        dv = v["device"]
        if not dv:
            del v["device"]
        elif isinstance(dv, str):
            v["device"] = dict(identifiers=dv.split(":"))

    await obj.conn.d_set(cp, v)


set_.__doc__ = """
    Add or modify a device.

    Boolean states can be set with "-o NAME" and cleared with "-o -name".
    Known types: {}
    """.format(" ".join(_types.keys()))


@cli.command(help="Display a device, list devices")
@click.pass_obj
@click.option("-c", "--cmd", is_flag=True, help="Use command-line names")
@click.argument("typ", nargs=1)
@click.argument("path", nargs=1)
async def get(obj, typ, path, cmd):
    if typ == "-":
        async for name in obj.conn.d_list(obj.hass_name):
            print(name, file=obj.stdout)
        return
    try:
        t = _types[typ]
    except KeyError:
        raise click.UsageError("I don't know this type.") from None

    if cmd:
        tt = {}
        for k, v in t.items():
            tt[v[3]] = k

        def cmd(x):
            return tt.get(x, x)

    else:

        def cmd(x):
            return x

    cp = obj.hass_name / typ
    if path == "-":
        async for name in obj.conn.d_list(cp):
            dp = cp + P(name)
            try:
                val = await obj.conn.d_get(dp | "config")
            except KeyError:
                continue
            if val is NotGiven:
                continue
            print(val["name"], typ, name, file=obj.stdout)
        return

    path = P(path)
    try:
        val = await obj.conn.d_get(cp + path | "config")
    except KeyError:
        print("Not found.")
        return
    if val is NotGiven:
        print("Not found.")
        return
    for k, v in val.items():
        print(cmd(k), v, file=obj.stdout)


get.__doc__ = """
    Display a device's configuration.

    Known types: {}
    """.format(" ".join(_types.keys()))


@cli.command(help="Delete a device")
@click.pass_obj
@click.argument("typ", nargs=1)
@click.argument("path", nargs=1)
async def delete(obj, typ, path):
    """Delete a device."""

    path = P(path)
    if typ not in _types:
        raise click.UsageError("I don't know this type.")

    cp = obj.hass_name / typ + path

    try:
        val = await obj.conn.d_get(cp | "config")
    except KeyError:
        print("Not found.")
        return
    if val is NotGiven:
        print("Not found.")
        return
    await obj.conn.d.delete(cp, rec=True)
