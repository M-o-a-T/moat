#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys

from moat.util import Path, attrdict, yprint

d = attrdict()
with open(sys.argv[1]) as f:
    r = csv.reader(f, dialect=csv.excel_tab)
    next(r)  # heading
    for r in csv.reader(f, dialect=csv.excel_tab):
        e = {int(r[1]): r[2]}
        d = d._update(Path("enum", r[0]), e)

yprint(d)
