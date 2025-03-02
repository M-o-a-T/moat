import sys, os
from build123d import *
from pathlib import Path
import math
#from bd_warehouse.gear import InvoluteToothProfile, SpurGear, SpurGearPlan

import logging
log=logging.getLogger("moat.d3")

__all__=["AMIN","Loc","LocR","Cyl","Up","sin","cos","tan","atan","stack","show","quarter","gear_turn","read_step","read_stl","pos","li","lto",
         "RX","RX1","RX2","RX3",
         "RY","RY1","RY2","RY3",
         "RZ","RZ1","RZ2","RZ3",
         "R0","R1","R2","R3",
         ]

AMIN={"align":(Align.MIN,Align.MIN,Align.MIN)}
def Loc(a,b,c):
    """
    Shorthand for Location.
    """
    return Location((a,b,c))

def LocR(d,a,h=0):
    """
    Locate radially, distance d, angle a, clockwise from top.
    """
    a=a*math.pi/180
    return Loc(d*math.sin(a),d*math.cos(a),h)

def Cyl(d,h):
    """
    A cylinder with diameter d and height h, centered but with +z.
    """
    return Cylinder(d/2,h,align=(Align.CENTER,Align.CENTER,Align.MIN))

def Up(z):
    """
    Move up.
    """
    return Location((0,0,z))

def sin(a):
    "sin (angle in degrees)"
    return math.sin(a*math.pi/180)

def cos(a):
    "cos (angle in degrees)"
    return math.cos(a*math.pi/180)

def tan(a):
    "tan (angle in degrees)"
    return math.tan(a*math.pi/180)

def atan(a,b=None):
    "tan⁻¹ (angle in degrees)"
    return (math.atan(a) if b is None else math.atan2(a,b))*180/math.pi


def stack(*x):
    """
    Sequence of 2d things, loft-ed.

    A x B y C: place A at zero, B at x, C at x+y. Loft them.
    A B: complete the object at A and start another at B.
    A x None: duplicate A x-up.
    """
    obj=Part()
    d=None
    p=0
    i=iter(x)
    d = last_shape = next(i)
    did_num=False
    for w in i:
        if isinstance(w,(int,float)):
            if did_num:
                raise ValueError("two consecutive numbers?")
            p += w
            did_num=True
        elif did_num:
            if w is None:
                w = last_shape
            else:
                last_shape = w
            nd = Up(p)*w
            obj += loft([d,nd])
            d = nd
            did_num=False
        elif w is None:
            raise ValueError("Real shape wanted")
        else:
            d = Up(p)*w
            last_shape = w
            did_num=False
    if did_num:
        raise ValueError("Trailing number")
    return obj

s_o = ...
def show(obj,name=None,dest=None):
    """
    Display this thing.

    If "dest" is a file or directory, write a STEP file there.
    """
    if name is None:
        name = f"{obj}_{(id(obj)/99)%10000}"

    global s_o
    if s_o is Ellipsis:
        import inspect
        f = inspect.currentframe()
        while f is not None and "show_object" not in f.f_globals:
            f = f.f_back
        s_o = f.f_globals["show_object"]
    s_o(obj.wrapped,name)

    if dest is not None:
        dest = Path(dest)
        if dest.is_dir():
            dest /= f"{name}.step"
        export_step(obj,str(dest))

def read_step(name):
    """
    Read this STEP file.
    """
    return import_step(name)

def read_stl(name):
    """
    Read this STL file.
    """
    return import_stl(name)

def quarter(res):
    """
    Given an object in the +x/+y quarter, mirror it twice.
    """
    res_xz=mirror(res,about=Plane.XZ)
    return (res
      +res_xz
      +mirror(res_xz+res,about=Plane.YZ)
      )

    
def gear_turn(n1, a1, n2, a2, minimize=True):
    """
    Given gear1 with n1 teeth, turned to angle a1, and gear2 with n2 teeth positioned at angle a2 relative to gear 1:
    how far do we turn gear2 so that its teeth mesh with gear1?
    
    This code assumes that 0° means the same thing for both gears (e.g. center of a tooth).
    
    If @minimize is true (the default), the resulting angle will be between 0 and 360/n2.
    """
    # step 1, assume that gear 2 sits on top of gear 1: turn gear 2 by 180° plus half a tooth.
    res = 180*(1+1/n2)  # 180+360/n2/2
    
    # step 2, turn gear 1 counterclockwise by a1, which turns gear 2 clockwise by the gear ratio.
    res += a1 * (n1/n2)
    
    # step 3, physically move gear2 around clockwise
    res += a2 * (1+n1/n2)
    
    # step 4, gear 2 is rotationally symmetric
    if minimize:
        res %= 360/n2

    return res

def pos(x=None,y=None):
    "Line drawing et al. Start position."
    ctx = BuildLine._get_context(log=False)
    try:
        res = ctx._mt_pos
    except AttributeError:
        if x is None:
            raise
        res = None
    if y is not None:
        ctx._mt_pos = (x,y)
    return res

def lto(x=None,y=None):
    ctx = BuildLine._get_context(log=False)
    p = ctx._mt_pos
    if x is None:
        x=p[0]
    if y is None:
        y=p[1]
    p2 = (x,y)
    ctx._mt_pos = p2
    Line(p,p2)

def li(x=0,y=0):
    ctx = BuildLine._get_context(log=False)
    p = ctx._mt_pos
    p2 = (p[0]+x,p[1]+y)
    ctx._mt_pos = p2
    Line(p,p2)

def RX(x):
    return Rot(90*x,0,0)
RX1=RX(1)
RX2=RX(2)
RX3=RX(3)
def RY(x):
    return Rot(0,90*x,0)
RY1=RY(1)
RY2=RY(2)
RY3=RY(3)
def RZ(x):
    return Rot(0,0,90*x)
RZ0=R0=RZ(0)
RZ1=R1=RZ(1)
RZ2=R2=RZ(2)
RZ3=R3=RZ(3)

AL=(Align.CENTER,Align.CENTER,Align.MIN)

