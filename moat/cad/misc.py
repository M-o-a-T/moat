"""
Miscellaneous helpers.
"""

from __future__ import annotations

try:
    import cadquery as cq
except ImportError:
    cq = None

__all__ = ["Mount", "Ridge", "Slider", "WoodScrew"]

import contextlib
from math import pi, tan

with contextlib.suppress(ImportError):
    from .things import Cone


def rad(a):
    return a * pi / 180


def Ridge(length, width, inset=0):
    """
    Returns a triangular profile for slide-ins etc.
    """
    r = cq.Workplane("XY").moveTo(0, 0)
    if inset < 0:
        r = r.line(-inset, 0)
    r = r.line(width, width).line(-width, width)
    if inset < 0:
        r = r.line(inset, 0)
    r = r.close().extrude(length)
    return r


def Slider(x, y, size=2, inset=0, chamfer=None, back=True, centered=True):
    """
    Returns a workplane with a slide-in guide open at -Y, centered on the origin.

    Set "inset" to whatever tolerance you need, for the subtractive part.

    @chamfer is None (sharp end, default), False (flat end) or True (chamfered).
    Set @back to False if you don't want/need the third side.
    """

    cap = -size if chamfer else size if chamfer is None else 0

    # sliders
    def hook(ws, offset, length):
        d = -1 if offset > 0 else 1
        ws = (
            ws.moveTo(offset, 0)
            .line(0, size * 3 + cap + inset)
            .line(d * (size), -cap)
            .line(d * (size + inset), -size - inset)
            .line(-d * size, -size)
            .line(0, -size)
            .close()
            .extrude(length)
        )
        return ws

    h1 = hook(cq.Workplane("XZ"), x, -y)
    h2 = hook(cq.Workplane("XZ"), 0, -y)
    res = h1.union(h2, clean=False)
    if back:
        h3 = hook(cq.Workplane("YZ"), y, x)
        res = res.union(h3, clean=False)
    elif back is None:
        h3 = (
            cq.Workplane("XY")
            .box(x, size * 3, size * 3, centered=False)
            .translate((0, y - size * 3, 0))
        )
        res = res.union(h3)
    if centered:
        res = res.translate((-x / 2, -y / 2, 0))
    return res.clean()


def Mount(length, inner, outer=None, cone=0):
    """A simple ring around a hole"""
    if outer is None:
        outer = inner * 1.2
    ws = cq.Workplane("XY").circle((outer + cone) / 2).extrude(length - cone)
    if cone:
        ws = (
            ws.faces(">Z")
            .workplane()
            .circle((outer + cone) / 2)
            .workplane(offset=cone)
            .circle(2)
            .loft()
        )
    ws = ws.faces(">Z").workplane().circle(inner / 2).cutThruAll()
    return ws


def WoodScrew(height, outer, inner, angle=45, head=None, negate=False):
    """The mount for a wood screw, i.e. one with a non-flat head.

    Hole not included.

    The mount is @height high and has @outer diameter. The screw's diameter
    is @inner and the head's @angle starts at the @head (diameter)'s edge.
    """
    if head is None:
        head = inner * 3 / 2

    h_head = (head - inner) / 2 * tan(rad(angle))

    if negate:
        return (
            cq.Workplane("XY")
            .at(0, 0)
            .circle(inner / 2)
            .extrude(height)
            .add(
                Cone(inner / 2, head / 2, (head - inner) / 2 * tan(rad(angle))).off_z(
                    height - h_head,
                ),
            )
        )

    ws = (
        cq.Workplane("XY")
        .at(0, 0)
        .circle(outer / 2)
        .circle(inner / 2)
        .extrude(height)
        # .faces(">Z").workplane()
        # .circle(head/2)
        .cut(
            Cone(inner / 2, head / 2, (head - inner) / 2 * tan(rad(angle))).off_z(height - h_head),
        )
    )

    return ws
