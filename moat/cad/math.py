"""
Random funky cadquery math
"""

from __future__ import annotations

try:
    import cadquery as cq
    import numpy as np
except ImportError:
    cq = None


def rotate(v, k, theta):
    "rotate vector @v around axis @k at angle @theta(degrees)"
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


def _copy(self):
    "returns a copy of a plane"
    return cq.Plane(origin=self.origin, xDir=self.xDir, normal=self.zDir)


def _translated(self, x, y=None):
    if y is None:
        v = cq.Vector(x[0], x[1], 0)
    else:
        v = cq.Vector(x, y, 0)
    w = self.newObject(self.all())
    w.plane = self.plane.copy()
    w.plane.setOrigin2d(v.x, v.y)
    return w


def _rotated(self, theta, center=None):
    "return a rotated workspace"
    p = self.plane
    w = self.newObject(self.all())
    if center is not None:
        raise NotImplementedError("Math")
    p = p.rotated((0, 0, theta))
    # cq.Plane(origin=p.origin,xDir=rotate(p.xDir,p.normal,theta),normal=p.normal)
    w.plane = p
    return w


def _wp(self, *a, **k):
    return self.copyWorkplane(cq.Workplane(*a, **k))


def _at(self, x, y=None, z=0):
    "move the Z offset"
    if y is not None:
        x = cq.Vector(x, y, z)
    return self.pushPoints((x,))


def _rot(self, angle, end):
    return self.rotate((0, 0, 0), end, angle)


if cq is not None:
    cq.Plane.copy = _copy
    cq.Workplane.translated = _translated
    cq.Workplane.rotated = _rotated
    cq.Workplane.at = _at
    cq.Workplane.wp = _wp
    cq.Workplane.rot_x = lambda s, a: _rot(s, a, (1, 0, 0))
    cq.Workplane.rot_y = lambda s, a: _rot(s, a, (0, 1, 0))
    cq.Workplane.rot_z = lambda s, a: _rot(s, a, (0, 0, 1))

    cq.Workplane.off_x = lambda s, x: s.translate((x, 0, 0))
    cq.Workplane.off_y = lambda s, y: s.translate((0, y, 0))
    cq.Workplane.off_z = lambda s, z: s.translate((0, 0, z))

    _S = cq.occ_impl.shapes.Shape
    _S.rot_x = lambda s, a: _rot(s, a, (1, 0, 0))
    _S.rot_y = lambda s, a: _rot(s, a, (0, 1, 0))
    _S.rot_z = lambda s, a: _rot(s, a, (0, 0, 1))

    _S.off_x = lambda s, x: s.translate((x, 0, 0))
    _S.off_y = lambda s, y: s.translate((0, y, 0))
    _S.off_z = lambda s, z: s.translate((0, 0, z))
