"""
Support code for tests
"""

from __future__ import annotations

import anyio
import os
import pytest

from moat.util import yload, merge


def as_attr(d, **kw):  # noqa:D103
    return merge(yload(d, attr=True), kw, replace=True)


## Standard config for tests
# apps:
#   c: bms._test.Cell

CF = """
c:
  c: 0.5
  t: 25
  cap: 2000
  i:
    dis: -1
    chg: 0
  lim:
    t:
      abs:
        min: 0
        max: 45
      ext:
        min: 10
        max: 40
    c:
      min: 0.25
      max: 0.75
    p:  # exponent when 'ext' limit is exceeded
      min: 2
      max: 2
    u:
      abs:
        min: 1
        max: 9
      std:
        min: 3
        max: 7
      ext:
        min: 2
        max: 8
"""

CF = as_attr(CF)
