#!/usr/bin/env python3  # noqa: D100
from __future__ import annotations

import csv
import sys

from moat.util import attrdict, yprint
from moat.lib.path import Path

d = attrdict()
with open(sys.argv[1]) as f:
    r = csv.reader(f, dialect=csv.excel_tab)
    next(r)  # heading
    for r in csv.reader(f, dialect=csv.excel_tab):
        e = attrdict(register=int(r[0]), reg_type="d", _doc=r[3])
        a, b = r[2].split(".")
        a, b = int(a), int(b)
        d = d.update_(Path.build(("alarm", a, b)), e)

yprint(d)
