#!/usr/bin/env python3

from moat.util import yprint, attrdict, P, Path, yload
import csv
import sys

with open("inc/enum.yaml","r") as f:
    enums = yload(f, attr=True).enum

import click
@click.command()
@click.option("-i","--info")
def main(info):
    d = attrdict()
    if not info:
        d.info = {"include": [
            "inc/enum.yaml",
            "inc/alarm.yaml",
            # "inc/modbus.yaml",
        ]}
        d.alarms = {"ref": [
            P("info.alarm"),
            # P("info.modbus"),
        ]}
        d.ref = P("info.universal")

    r = csv.reader(sys.stdin, dialect=csv.excel_tab)
    next(r) # heading
    for r in csv.reader(sys.stdin, dialect=csv.excel_tab):
        p=P(r[4].lower())
        pa = p[1].split("_")
        if pa[0] in ("i","sw","o","do","di"):
            p = P(p[0]) + Path(*pa) + p[2:]
        elif pa[0] in ("alarme","anlage","modbus"):
            pa = p[1].split("_",1)
            p = P(p[0]) + Path(*pa) + p[2:]
        if r[3] in ("s16","s32"):
            tt="int"
        elif r[3] in ("u8", "u16","u32"):
            tt="uint"
        else:
            raise ValueError(f"Unknown type: {r[3] !r}")

        e = attrdict(register=int(r[0]), len=int(r[1]), type=tt, reg_type="i" if r[2] == "04" else "h", _doc=r[6])
        u = r[8]
        s = 0
        if u in enums:
            e["values"] = {"ref": Path("info","enum") / u}
        else:
            if u.startswith("1/1000"):
                s = -3
                u = u[6:]
            elif u.startswith("1/100"):
                s = -2
                u = u[5:]
            elif u.startswith("1/10"):
                s = -1
                u = u[4:]
            if u in ("kW","kWh"): # kg
                u = u[1:]
                s += 3
            if u == "%":
                s -= 2
                u = ""
            if u:
                e.unit = u
            if s:
                e.scale = s
        if info:
            pp = P(info)
        else:
            pp = P("regs")
        d = d._update(pp + p,e)

    yprint(d)
main()
