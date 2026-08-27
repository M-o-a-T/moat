"""
Collection of useful shortcuts for 3D modelling with build123d.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from build123d import (
    Align,
    Axis,
    BuildLine,
    Cone,
    Cylinder,
    Intrinsic,
    JernArc,
    Line,
    Location,
    Matrix,
    Part,
    Plane,
    RegularPolygon,
    Rot,
    Shape,
    Vector,
    export_step,
    export_stl,
    import_step,
    import_stl,
    loft,
    mirror,
)

from moat.util import InexactFloat

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import EllipsisType

    from collections.abc import Callable

log = logging.getLogger("moat.d3")

__all__ = [
    "ACCM",
    "AMIN",
    "R0",
    "R1",
    "R2",
    "R3",
    "RX",
    "RX1",
    "RX2",
    "RX3",
    "RY",
    "RY1",
    "RY2",
    "RY3",
    "RZ",
    "RZ1",
    "RZ2",
    "RZ3",
    "ArcAt",
    "Cyl",
    "D",
    "Loc",
    "LocR",
    "PolyCap",
    "RotAxis",
    "RotateTo",
    "Up",
    "atan",
    "cos",
    "gear_turn",
    "li",
    "lto",
    "pos",
    "quarter",
    "read_step",
    "read_stl",
    "show",
    "sin",
    "stack",
    "tan",
]

AMIN = {"align": (Align.MIN, Align.MIN, Align.MIN)}
ACCM = {"align": (Align.CENTER, Align.CENTER, Align.MIN)}


def D(n: float, **kw: Any) -> InexactFloat:
    """
    A wrapper for :class:`moat.util.InexactFloat`. Saves on typing.
    """
    return InexactFloat(n, **kw)


def Loc(a: float, b: float, c: float) -> Location:
    """
    Shorthand for Location.
    """
    return Location((a, b, c))


def LocR(d: float, a: float, h: float = 0) -> Location:
    """
    Locate radially, distance d, angle a, clockwise from top.
    """
    a = a * math.pi / 180
    return Loc(d * math.sin(a), d * math.cos(a), h)


def Cyl(d: float, h: float, d2: float | None = None) -> Cone | Cylinder:
    """
    A cylinder with diameter d and height h, centered but with +z.
    """
    if d2 is not None and d2 != d:
        return Cone(d / 2, d2 / 2, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return Cylinder(d / 2, h, align=(Align.CENTER, Align.CENTER, Align.MIN))


def Up(z: float) -> Location:
    """
    Move something up. Shorthand for Location(0,0,z).
    """
    return Location((0, 0, z))


def ArcAt(
    line: Shape, radius: float, angle: float = 90, twist: float = 0, at_end: bool = True
) -> Shape:
    """
    Add an arc to the end of a path. @twist modifies the direction the arc
    bends towards.
    """
    res = JernArc((0, 0, 0), (0, 1, 0), radius, angle)
    res = RX1 * Rot(0, twist, 0) * res

    if at_end:
        return Location(line @ 1) * RotateTo(res, line % 1)  # ty:ignore[unsupported-operator]
    return Location(line @ 0) * RotateTo(res, -(line % 0))  # ty:ignore[unsupported-operator]

    # Location(line@.9)*Rot(line%1)*JernArc((0,0,0),(1,0,0),radius,angle)
    # Rot(0,0,twist)*


def PolyCap(d: float, n: int = 6) -> Part:
    """
    Given a polygonal rod, this returns its end cap.
    """
    al = (Align.CENTER, Align.CENTER)
    return stack(RegularPolygon(d / 2, n, align=al), d / 4, RegularPolygon(d / 4, n, align=al))


def RotateTo(thing: Shape, direction: Vector) -> Shape:  # noqa:D103
    ax = Axis((0, 0, 0), Vector(0, 0, 1) + direction.normalized())
    return thing.rotate(ax, 180)


def RotAxis(axis: Axis, angle: float) -> Rot:
    """
    Rotation matrix for this angle around that axis.
    """
    from transforms3d.euler import mat2euler  # noqa: PLC0415

    rtm = Matrix()
    breakpoint()  # noqa:T100
    rtm.rotate(axis, angle)
    rtm = [[rtm[x, y] for y in range(3)] for x in range(3)]
    rtm = [a * 180 / math.pi for a in mat2euler(rtm, "szyx")]
    return Rot(tuple(rtm), Intrinsic.XYZ)


def sin(a: float) -> float:
    """sin (angle in degrees)"""
    return math.sin(a * math.pi / 180)


def cos(a: float) -> float:
    """cos (angle in degrees)"""
    return math.cos(a * math.pi / 180)


def tan(a: float) -> float:
    """tan (angle in degrees)"""
    return math.tan(a * math.pi / 180)


def atan(a: float, b: float | None = None) -> float:
    """tan⁻¹ (angle in degrees)"""
    return (math.atan(a) if b is None else math.atan2(a, b)) * 180 / math.pi


def stack(*x: float | Shape | None) -> Part:
    """
    A sequence of 2d things, loft-ed.

    A z1 B z2 C: place shape A at z=0, shape B at z=z1, shape C at z=z1+z2. Loft them.
    A B: complete the object with shape A and start another with shape B.
    A z None: shorthand for A z A.
    """
    obj = Part()
    d: Shape | None = None
    p = 0.0
    i = iter(x)
    first = next(i)
    assert isinstance(first, Shape)
    last_shape: Shape | None = first
    d = last_shape
    did_num = False
    for w in i:
        if isinstance(w, (int, float)):
            if did_num:
                raise ValueError("two consecutive numbers?")
            p += w
            did_num = True
        elif did_num:
            if w is None:
                w = last_shape  # noqa:PLW2901
            else:
                last_shape = w
            assert w is not None
            nd: Shape = Up(p) * w
            assert d is not None
            obj += loft([d, nd])  # ty:ignore[invalid-argument-type]
            d = nd
            did_num = False
        elif w is None:
            raise ValueError("Real shape wanted")
        else:
            d = Up(p) * w
            last_shape = w
            did_num = False
    if did_num:
        raise ValueError("Trailing number")
    return obj


s_o: Callable[..., None] | EllipsisType | None = ...


def show(obj: Shape, name: str | None = None, dest: str | Path | None = None) -> None:
    """
    Display this thing.

    If "dest" is a file or directory, write a STEP file there.
    """
    if name is None:
        name = f"{obj}_{(id(obj) / 99) % 10000}"

    global s_o
    if s_o is Ellipsis:
        import inspect  # noqa: PLC0415

        f = inspect.currentframe()
        while f is not None and "show_object" not in f.f_globals:
            f = f.f_back
        s_o = None if f is None else f.f_globals["show_object"]
    if s_o is not None:
        s_o(obj, name)

    if dest is not None:
        dest_p = Path(dest)
        if dest_p.is_dir():
            export_stl(obj, str(dest_p / f"{name}.stl"))
            dest_p /= f"{name}.step"

        export_step(obj, str(dest_p))


def read_step(name: str | Path) -> Shape:
    """
    Read this STEP file.
    """
    return import_step(name)


def read_stl(name: str | Path) -> Shape:
    """
    Read this STL file.
    """
    return import_stl(name)


def quarter(res: Shape) -> Shape:
    """
    Given an object in the +x/+y quarter, mirror it twice.
    """
    res_xz = mirror(res, about=Plane.XZ)  # ty:ignore[invalid-argument-type]
    return res + res_xz + mirror(res_xz + res, about=Plane.YZ)


def gear_turn(n1: int, a1: float, n2: int, a2: float, minimize: bool = True) -> float:
    """
    Given gear1 with n1 teeth, turned to angle a1, and gear2 with n2 teeth
    positioned at angle a2 relative to gear 1: how far do we need to turn
    gear2 so that its teeth mesh with gear1?

    This code assumes that 0° means the same thing for both gears (e.g. center of a tooth).

    If @minimize is true (the default), the resulting angle will be between 0 and 360/n2.
    """
    # step 1, place gear 2 on top of gear 1: we need to turn gear 2 by 180° plus half a tooth.
    res = 180 * (1 + 1 / n2)  # 180+360/n2/2

    # step 2, turn gear 1 clockwise by a1, which turns gear 2 counterclockwise by the gear ratio.
    res -= a1 * (n1 / n2)

    # step 3, move gear 2 to its correct position clockwise, which causes it
    # to turn clockwise by the gear ratio plus one.
    res += a2 * (1 + n1 / n2)

    # step 4, gear 2 is rotationally symmetric
    if minimize:
        res %= 360 / n2

    return res


def pos(x: float | None = None, y: float | None = None) -> tuple[float, float] | None:
    """Line drawing et al. Start position."""
    ctx = BuildLine._get_context(log=False)  # noqa: SLF001
    res: tuple[float, float] | None
    try:
        res = ctx._mt_pos  # noqa: SLF001  # ty:ignore[unresolved-attribute]
    except AttributeError:
        if x is None:
            raise
        res = None
    if y is not None and ctx is not None:
        ctx._mt_pos = x, y  # noqa: SLF001  # ty:ignore[unresolved-attribute]
    return res


def lto(x: float | None = None, y: float | None = None) -> None:
    """Line to absolute position"""
    ctx = BuildLine._get_context(log=False)  # noqa: SLF001
    if ctx is None:
        raise RuntimeError("No BuildLine context")
    p: tuple[float, float] = ctx._mt_pos  # noqa: SLF001
    if x is None:
        x = p[0]
    if y is None:
        y = p[1]
    p2 = (x, y)
    ctx._mt_pos = p2  # noqa: SLF001  # ty:ignore[unresolved-attribute]
    Line(p, p2)


def li(x: float = 0, y: float = 0) -> None:
    """Relative line"""
    ctx = BuildLine._get_context(log=False)  # noqa: SLF001
    if ctx is None:
        raise RuntimeError("No BuildLine context")
    p: tuple[float, float] = ctx._mt_pos  # noqa: SLF001
    p2 = (p[0] + x, p[1] + y)
    ctx._mt_pos = p2  # noqa: SLF001  # ty:ignore[unresolved-attribute]
    Line(p, p2)


def RX(x: int) -> Rot:
    """Rotate 90°*x"""
    return Rot(90 * x, 0, 0)


RX1 = RX(1)
RX2 = RX(2)
RX3 = RX(3)


def RY(y: int) -> Rot:
    """Rotate 90°*y"""
    return Rot(0, 90 * y, 0)


RY1 = RY(1)
RY2 = RY(2)
RY3 = RY(3)


def RZ(z: int) -> Rot:
    """Rotate 90°*z"""
    return Rot(0, 0, 90 * z)


RZ0 = R0 = RZ(0)
RZ1 = R1 = RZ(1)
RZ2 = R2 = RZ(2)
RZ3 = R3 = RZ(3)

AL = (Align.CENTER, Align.CENTER, Align.MIN)
