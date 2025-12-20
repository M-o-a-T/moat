"Your description here"

from __future__ import annotations

from math import sqrt  # noqa:F401

from build123d import *  # noqa:F403
from build123d import Align, Box

from moat.d3 import *  # noqa:F403
from moat.d3 import show

ACM = (Align.CENTER, Align.CENTER, Align.MIN)

b = Box(1, 2, 3, align=ACM)
show(b, "Box")
