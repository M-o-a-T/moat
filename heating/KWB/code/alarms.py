#!/usr/bin/env python3

from moat.util import yprint, attrdict, P, Path
import csv
import sys

d = attrdict()
r = csv.reader(sys.stdin, dialect=csv.excel_tab)
next(r) # heading
for r in csv.reader(sys.stdin, dialect=csv.excel_tab):
    e = attrdict(register=int(r[0]), reg_type="d", _doc=r[3])
    a,b = r[2].split(".")
    a,b = int(a), int(b)
    d = d._update(Path("alarm",a,b),e)

yprint(d)
