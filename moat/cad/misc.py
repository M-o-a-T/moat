"""
Miscellaneous helpers.
"""

from __future__ import annotations

import contextlib
from math import pi, tan

from typing import Any

try:
    import cadquery as cq
except ImportError:
    cq = None  # ty:ignore[invalid-assignment,misc]  # optional import

__all__ = ["Mount", "Ridge", "Slider", "WoodScrew"]


with contextlib.suppress(ImportError):
    from .things import Cone


def rad(a: float) -> float:
    """Convert degrees to radians."""
    return a * pi / 180


def Ridge(length: float, width: float, inset: float = 0) -> Any:
    """
    Returns a triangular profile for slide-ins etc.
    """
    r: Any = cq.Workplane("XY").moveTo(0, 0)
    if inset < 0:
        r = r.line(-inset, 0)
    r = r.line(width, width).line(-width, width)
    if inset < 0:
        r = r.line(inset, 0)
    r = r.close().extrude(length)
    return r


def Slider(
    x: float,
    y: float,
    size: float = 2,
    inset: float = 0,
    chamfer: bool | None = None,
    back: bool | None = True,
    centered: bool = True,
) -> Any:
    """
    Returns a workplane with a slide-in guide open at -Y, centered on the origin.

    Set "inset" to whatever tolerance you need, for the subtractive part.

    @chamfer is None (sharp end, default), False (flat end) or True (chamfered).
    Set @back to False if you don't want/need the third side.
    """

    cap: float = -size if chamfer else size if chamfer is None else 0

    # sliders
    def hook(ws: Any, offset: float, length: float) -> Any:
        d = -1 if offset > 0 else 1
        ws = (
            ws
            .moveTo(offset, 0)
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
    res: Any = h1.union(h2, clean=False)
    if back:
        h3 = hook(cq.Workplane("YZ"), y, x)
        res = res.union(h3, clean=False)
    elif back is None:
        h3 = (
            cq
            .Workplane("XY")
            .box(x, size * 3, size * 3, centered=False)
            .translate((0, y - size * 3, 0))
        )
        res = res.union(h3)
    if centered:
        res = res.translate((-x / 2, -y / 2, 0))
    return res.clean()


def Mount(length: float, inner: float, outer: float | None = None, cone: float = 0) -> Any:
    """A simple ring around a hole"""
    if outer is None:
        outer = inner * 1.2
    ws: Any = cq.Workplane("XY").circle((outer + cone) / 2).extrude(length - cone)
    if cone:
        ws = (
            ws
            .faces(">Z")
            .workplane()
            .circle((outer + cone) / 2)
            .workplane(offset=cone)
            .circle(2)
            .loft()
        )
    ws = ws.faces(">Z").workplane().circle(inner / 2).cutThruAll()
    return ws


def WoodScrew(
    height: float,
    outer: float,
    inner: float,
    angle: float = 45,
    head: float | None = None,
    negate: bool = False,
) -> Any:
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
            cq
            .Workplane("XY")
            .at(0, 0)  # ty:ignore[unresolved-attribute]
            .circle(inner / 2)
            .extrude(height)
            .add(
                Cone(inner / 2, head / 2, (head - inner) / 2 * tan(rad(angle))).off_z(
                    height - h_head,
                ),
            )
        )

    ws: Any = (
        cq
        .Workplane("XY")
        .at(0, 0)  # ty:ignore[unresolved-attribute]
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
