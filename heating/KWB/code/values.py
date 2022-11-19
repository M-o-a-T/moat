#!/usr/bin/env python3

from moat.util import yprint, attrdict, P, Path
import csv
import sys

d = attrdict()
r = csv.reader(sys.stdin, dialect=csv.excel_tab)
next(r) # heading
for r in csv.reader(sys.stdin, dialect=csv.excel_tab):
    e = {int(r[1]): r[2]}
    d = d._update(Path("enum",r[0]),e)

yprint(d)
