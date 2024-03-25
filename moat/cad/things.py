import cadquery as cq

__all__ = ["Box","Cone","Cylinder","Loft","Sphere","Torus","Wedge"]

Box = cq.Solid.makeBox
Cone = cq.Solid.makeCone
Cylinder = cq.Solid.makeCylinder
Loft = cq.Solid.makeLoft
Sphere = cq.Solid.makeSphere
Torus = cq.Solid.makeTorus
Wedge = cq.Solid.makeWedge
