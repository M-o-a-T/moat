"""
A simple round screen for my bird feeder.
"""

from __future__ import annotations

from math import atan, cos, sqrt, tan

from build123d import Align, Box, Circle, Torus

from moat.d3 import Cyl, Loc, Rot, show, stack

ACM = (Align.CENTER, Align.CENTER, Align.MIN)

top = False

r1 = 5
r2 = 150
h = 70
wall = 1.5
a = atan(r2 - r1, h)
wx = wall / cos(a)

if top:
    r1 = 1.5
    r2 = 12
    h = (r2 - r1) / tan(a)

b = stack(Circle(r1), h, Circle(r2))
b -= Loc(0, 0, wall) * stack(Circle(r1), h - wall, Circle(r2 - wx))
b -= Cyl(r1 * 2, wall)
if not top:
    b += Box(r1 * 2, wall, wall, align=ACM)
    b += Loc(0, 0, h / 2) * Rot(0, 45, 0) * Torus(r1 / 2, wall / 2)
    b += Loc(r1 / 2 / sqrt(2), 0, 0) * Cyl(wall, h / 2 - r1 / 2 / sqrt(2))
show(b, "Box", f"/tmp/{'top' if top else 'bot'}.step")
