"""
Random funky cadquery math
"""

from __future__ import annotations

from typing import Any

try:
    import cadquery as cq
    import numpy as np
    from cadquery.occ_impl import shapes as cqs
except ImportError:
    cq = None  # ty:ignore[invalid-assignment,misc]  # optional import


def rotate(v: Any, k: Any, theta: float) -> Any:
    """rotate vector @v around axis @k at angle @theta(degrees)"""
    v = v.toTuple()
    k = k.toTuple()
    theta *= np.pi / 180

    v = np.asarray(v)
    k = np.asarray(k) / np.linalg.norm(k)  # Normalize k to a unit vector
    cos_theta = np.cos(theta)
    sin_theta = np.sin(theta)

    term1 = v * cos_theta
    term2 = np.cross(k, v) * sin_theta
    term3 = k * np.dot(k, v) * (1 - cos_theta)

    return cq.Vector(tuple(term1 + term2 + term3))


def _copy(self: Any) -> Any:
    """returns a copy of a plane"""
    return cq.Plane(origin=self.origin, xDir=self.xDir, normal=self.zDir)


def _translated(self: Any, x: Any, y: float | None = None) -> Any:
    if y is None:
        v = cq.Vector(x[0], x[1], 0)
    else:
        v = cq.Vector(x, y, 0)
    w = self.newObject(self.all())
    w.plane = self.plane.copy()
    w.plane.setOrigin2d(v.x, v.y)
    return w


def _rotated(self: Any, theta: float, center: Any = None) -> Any:
    """return a rotated workspace"""
    w = self.newObject(self.all())
    if center is not None:
        raise NotImplementedError("Math")
    p = self.plane
    p = p.rotated((0, 0, theta))
    # cq.Plane(origin=p.origin,xDir=rotate(p.xDir,p.normal,theta),normal=p.normal)
    w.plane = p
    return w


def _wp(self: Any, *a: Any, **k: Any) -> Any:
    return self.copyWorkplane(cq.Workplane(*a, **k))


def _at(self: Any, x: Any, y: float | None = None, z: float = 0) -> Any:
    """move the Z offset"""
    if y is not None:
        x = cq.Vector(x, y, z)
    return self.pushPoints((x,))


def _rot(self: Any, angle: float, end: tuple[float, float, float]) -> Any:
    return self.rotate((0, 0, 0), end, angle)


if cq is not None:
    cq.Plane.copy = _copy  # ty:ignore[unresolved-attribute]
    cq.Workplane.translated = _translated  # ty:ignore[unresolved-attribute]
    cq.Workplane.rotated = _rotated  # ty:ignore[unresolved-attribute]
    cq.Workplane.at = _at  # ty:ignore[unresolved-attribute]
    cq.Workplane.wp = _wp  # ty:ignore[unresolved-attribute]
    cq.Workplane.rot_x = lambda s, a: _rot(s, a, (1, 0, 0))  # ty:ignore[unresolved-attribute]
    cq.Workplane.rot_y = lambda s, a: _rot(s, a, (0, 1, 0))  # ty:ignore[unresolved-attribute]
    cq.Workplane.rot_z = lambda s, a: _rot(s, a, (0, 0, 1))  # ty:ignore[unresolved-attribute]

    cq.Workplane.off_x = lambda s, x: s.translate((x, 0, 0))  # ty:ignore[unresolved-attribute]
    cq.Workplane.off_y = lambda s, y: s.translate((0, y, 0))  # ty:ignore[unresolved-attribute]
    cq.Workplane.off_z = lambda s, z: s.translate((0, 0, z))  # ty:ignore[unresolved-attribute]

    _S = cqs.Shape
    _S.rot_x = lambda s, a: _rot(s, a, (1, 0, 0))  # ty:ignore[unresolved-attribute]
    _S.rot_y = lambda s, a: _rot(s, a, (0, 1, 0))  # ty:ignore[unresolved-attribute]
    _S.rot_z = lambda s, a: _rot(s, a, (0, 0, 1))  # ty:ignore[unresolved-attribute]

    _S.off_x = lambda s, x: s.translate((x, 0, 0))  # ty:ignore[unresolved-attribute]
    _S.off_y = lambda s, y: s.translate((0, y, 0))  # ty:ignore[unresolved-attribute]
    _S.off_z = lambda s, z: s.translate((0, 0, z))  # ty:ignore[unresolved-attribute]
