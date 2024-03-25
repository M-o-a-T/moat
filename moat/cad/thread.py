from math import tan,pi
import cq_warehouse.thread as _t

__all__ = ["AngledThread"]

def AngledThread(radius, offset, apex=0, angle=45, external:bool=True, simple:bool=False, **kw):
    """
    Create a thread with a defined angle.

    @radius: the radius of the hole.
    @offset: the width of the thread.
    @pitch: distance between windings
    @length: length of screw / hole
    @apex: flat area on top (default zero)
    @angle: slope angle (default 45°).
    @external: screw or nut?
    @hand: "left" or "right"
    @end_finishes: 2-tuple of ["raw", "square", "fade", "chamfer"]
    """
    # TODO support tapered screws

    apex_radius = radius + offset * (1 if external else -1)
    root_width = tan(angle*pi/180)*offset*2 + apex

    return _t.Thread(
            apex_radius=apex_radius,
            apex_width=0,
            root_radius=radius,
            root_width=root_width,
            simple=simple,
            **kw)
