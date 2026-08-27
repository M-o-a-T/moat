"""
Miscellaneous solids.
"""

from __future__ import annotations

from typing import Any

try:
    import cadquery as cq
except ImportError:
    pass
else:
    __all__ = ["Box", "Cone", "Cylinder", "Loft", "Sphere", "Torus", "Wedge"]

    Box: Any = cq.Solid.makeBox
    Cone: Any = cq.Solid.makeCone
    Cylinder: Any = cq.Solid.makeCylinder
    Loft: Any = cq.Solid.makeLoft
    Sphere: Any = cq.Solid.makeSphere
    Torus: Any = cq.Solid.makeTorus
    Wedge: Any = cq.Solid.makeWedge
