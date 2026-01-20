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
        e = {int(r[1]): r[2]}
        d = d._update(Path.build(("enum", r[0])), e)  # noqa: SLF001

yprint(d)
