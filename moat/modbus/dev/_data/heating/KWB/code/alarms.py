#!/usr/bin/env python3

import csv
import sys

from moat.util import P, Path, attrdict, yprint

d = attrdict()
with open(sys.argv[1], "r") as f:
    r = csv.reader(f, dialect=csv.excel_tab)
    next(r)  # heading
    for r in csv.reader(f, dialect=csv.excel_tab):
        e = attrdict(register=int(r[0]), reg_type="d", _doc=r[3])
        a, b = r[2].split(".")
        a, b = int(a), int(b)
        d = d._update(Path("alarm", a, b), e, skip_empty=False)

yprint(d)
