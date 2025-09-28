"""
Helper for building a simple thread.
"""

from __future__ import annotations

from math import pi, tan

try:
    import bd_warehouse.thread as _t
    import cadquery
except ImportError:
    _t = None
    TrapezoidalThread = object
else:
    TrapezoidalThread = _t.TrapezoidalThread

__all__ = ["AngledThread", "ISO228_Thread"]

IN = 25.4  # mm per inch


def radians(x):
    return x * pi / 180


def AngledThread(
    radius,
    offset,
    apex=0,
    angle=45,
    external: bool = True,
    simple: bool = False,
    **kw,
):
    """
    Create a thread with a defined angle.

    The thread is always an add-on object. Thus, you should add
    internal threads to a hole with radius (@radius + @offset - 𝛆).

    @radius: the radius of the hole.
    @offset: the width of the thread.
    @pitch: distance between windings
    @length: length of screw / hole
    @apex: flat area on top (default zero)
    @angle: slope angle (default 45°).
    @external: screw or nut? (default True=screw)
    @hand: "left" or "right" (default "right")
    @end_finishes: 2-tuple of ["raw", "square", "fade", "chamfer"]
    """
    # TODO support tapered screws

    if external:
        apex_radius = radius + offset
    else:
        apex_radius = radius
        radius += offset
    root_width = tan(angle * pi / 180) * offset * 2 + apex

    fin = kw.get("end_finishes")
    if fin is not None and isinstance(fin, str):
        kw["end_finishes"] = fin.split(",")

    return _t.Thread(
        apex_radius=apex_radius,
        apex_width=0.1,
        root_radius=radius,
        root_width=root_width - 0.1,
        simple=simple,
        **kw,
    )


class ISO228_Thread(TrapezoidalThread):
    "Threads for fittings. ISO 228."

    specs = {
        # nominal size: threads per inch / diameter at center of thread
        "1/16": (28, 7.142),
        "1/8": (28, 9.147),
        "1/4": (19, 12.301),
        "3/8": (19, 15.806),
        "1/2": (14, 19.793),
        "5/8": (14, 21.749),
        "3/4": (14, 25.279),
        "7/8": (14, 29.039),
        "1": (11, 31.770),
        "1 1/8": (11, 36.418),
        "1 1/4": (11, 40.431),
        "1 1/2": (11, 46.324),
        "1 3/4": (11, 52.267),
        "2": (11, 58.135),
        "2 1/4": (11, 64.231),
        "2 1/2": (11, 73.705),
        "2 3/4": (11, 80.055),
        "3": (11, 86.405),
        "3 1/2": (11, 98.851),
        "4": (11, 111.551),
        "4 1/2": (11, 124.251),
        "5": (11, 136.951),
        "5 1/2": (11, 149.651),
        "6": (11, 162.351),
    }

    thread_angle = 27.5  # degrees

    @classmethod
    def parse_size(cls, x):
        "not called here. Yes we're duck typing."
        x  # noqa:B018
        raise RuntimeError("Not applicable")

    def __init__(
        self,
        size: str,
        length: float,
        adj: float = 0,
        external: bool = True,
        **kw,
    ):
        kw.setdefault("end_finishes", ("fade", "fade"))

        self.size = size
        self.external = external
        self.length = length
        (pitch, diameter) = self.specs[self.size]
        self.pitch = IN / pitch
        diameter += 2 * adj

        self.adj = adj

        # 1/6th of the total height, given the thread angle, is cut off.
        # This corresponds to 1/6th of the total width, i.e. the pitch.

        top = 1 / 6 * self.pitch
        apex_width = top
        root_width = self.pitch - top  # - bottom really, but top==bottom here

        # The height difference between the thread's center and its
        # adjacent top (or bottom) is spread over 1/6th of the pitch
        # length; the ratio is defined by the angle.

        hd = self.pitch / 6 / tan(radians(self.thread_angle))
        if self.external:
            self.apex_radius = diameter / 2 + hd
            self.root_radius = diameter / 2 - hd
            self.diameter = 2 * self.root_radius
        else:
            self.apex_radius = diameter / 2 - hd
            self.root_radius = diameter / 2 + hd
            self.diameter = 2 * self.apex_radius

        cq_object = _t.Thread(
            apex_radius=self.apex_radius,
            apex_width=apex_width,
            root_radius=self.root_radius,
            root_width=root_width,
            pitch=self.pitch,
            length=self.length,
            **kw,
        )
        self.end_finishes = cq_object.end_finishes
        self.hand = "right" if cq_object.right_hand else "left"
        cadquery.Solid.__init__(self, cq_object.wrapped)
