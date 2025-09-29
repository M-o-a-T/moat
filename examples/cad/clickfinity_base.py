"""
A base for Clickfinity.
"""
from __future__ import annotations

import os

from build123d import (
    Align,
    Axis,
    Box,
    BuildLine,
    BuildSketch,
    Circle,
    Cylinder,
    Line,
    Plane,
    Polygon,
    RadiusArc,
    Rectangle,
    chamfer,
    export_step,
    export_stl,
    extrude,
    make_face,
    mirror,
    revolve,
    show,
)

from moat.d3 import R0, R1, R2, R3, RX1, RY1, RY3, Loc, Rot, quarter, stack

#from math import sqrt

### basic grid parameters, Gridfinity standard
grid=42
# Radius
corner_r=4


# Profile
w1=2.85
h1=.7
w2=w1-h1
h2=1.8+h1
h3=h2+w2

# depth of noses
nose_len=w2*1.2
# heights of slot and nose
slot_h=h2*.75
nose_h=slot_h-.25

# width of the bar
bar_w=2*w1
# height of the bar
bar_h=h3


### The screw hole
# body diameter
screw_d = 3.15
# head diameter
screw_head_d = 5.85
# body length
screw_h = 1.5
# Is the head slanted (as in your standard wood screw)?
# False: cylinder
slant=True

def LG(x,y):  # noqa:D103
    return Loc(grid*x,grid*y,0)


base_profile=Polygon(
        (0,0),(w1,0),(w2,h1),(w2,h2),(0,h3),(0,0),
        align=(None,None))

base_profile_nf=Polygon(
        (0,0),(w2,0),(w2,h2),(0,h3),(0,0),
        align=(None,None))

base_profile_nf += mirror(base_profile,about=Plane.YZ)
base_profile += mirror(base_profile,about=Plane.YZ)

def corner():
    """
    The stuff in the corner of a box
    """
    def arc(d):
        with BuildSketch() as sk:
            with BuildLine():
                RadiusArc((corner_r,d),(d,corner_r),corner_r-d)
                if d:
                    Line((d,corner_r),(0,corner_r))
                Line((0,corner_r),(0,0))
                Line((0,0),(corner_r,0))
                if d:
                    Line((corner_r,0),(corner_r,d))

            make_face()
        return sk.sketch
    return stack(arc(w1),h1,arc(w2),h2-h1,None,h3-h2,arc(0.01))

def inner_corner():  # noqa:D103
    return quarter(corner())
C4=inner_corner()

def side_corner():  # noqa:D103
    return (corner()
            +Rot(0,0,90)*corner()
            +Loc(-corner_r,0,0)*R3*RX1*extrude(base_profile_nf,-corner_r*2)
            )
C3=side_corner()

def outer_corner():  # noqa:D103
    return  R2*Loc(-corner_r,-corner_r,0)*RX1*revolve(Loc(corner_r,0,0)*base_profile_nf, Axis.Y,90)
C2=outer_corner()

#show(side_corner(),"SC")
#show(outer_corner(),"oc")


def bar():
    """
    A grid bar.
    """
    b=Loc(corner_r,0,0)*R3*RX1*extrude(base_profile,2*corner_r-grid)

    #b=Box(grid,bar_w,bar_h,align=(Align.MIN,Align.CENTER,Align.MIN))
    #b=chamfer(b.edges().filter_by(Axis.X).group_by(Axis.Z)[-1],bar_w/3)


    # This controls the internal angle of the click head.
    x3=3.4

    # height of the click head
    hb=bar_h*.85

    # width of the head (its outside edge)
    wb=bar_w/1.6

    # inner edge of the "clicker"
    ib=bar_w/6

    # chamfer, top edge of the head
    ch=bar_w/3.3

    cut = Loc(grid/5,bar_w/15,0)*Box(grid/4,bar_w,bar_h,align=(Align.MIN,Align.MAX,Align.MIN))
    cut=chamfer(cut.edges().filter_by(Axis.Z),bar_w/6)
    b = b-cut-Loc(grid,0,0)*R2*cut

    bar_profile=Polygon((ib,0),(ib,bar_h-ib),(2.15,bar_h-2.15),(2.15,0),(ib,0),align=(None,None))
    bar=Loc(grid/5, 0,0)*RX1*RY3*extrude(bar_profile,grid/6.5)
    #bar=Loc(grid/5, -ib,0)*Box(grid/6.5,bar_w/2-ib,bar_h*.9,
    #  align=(Align.MIN,Align.MAX,Align.MIN))
    #bar=chamfer(bar.edges().filter_by(Axis.X).group_by(Axis.Z)[-1].group_by(Axis.Y)[0],1)

    f1=Polygon((0,ib),(0,wb),(hb-ch,wb),(hb,wb-ch),(hb,ib),(0,ib),
               align=(None,None))
    f2=Polygon((0,bar_w/x3),(0,wb),(hb-ch,wb),(hb,wb-ch),(hb,bar_w/x3),(0,bar_w/x3),
               align=(None,None))
    head=Loc(grid/6.5+grid/5,0,0)*RY1*R2*stack(f1,grid/13.5,f2)
    head = chamfer(head.edges().group_by(Axis.X)[0].sort_by(Axis.Y)[:2],bar_w/12)
    bar += head
    b = b+bar+Loc(grid,0,0)*R2*bar
    return b

def screw():
    """
    The hole for a screw.
    """
    if slant:
        return stack(Circle(screw_d/2),
                     screw_h,None,
                     (screw_head_d-screw_d)/2,Circle(screw_head_d/2),bar_h,None)
    return stack(Circle(screw_d/2),screw_h,None,Circle(screw_head_d/2),bar_h,None)

def R(w,h):
    "Rectangle. Laziness."
    return Rectangle(w,h, align=(Align.CENTER,Align.MIN))

def slot(d=0,h=slot_h):
    """
    This is the negative volume of an edge slot.
    """
    #((1.4,3),(1.4,2.2),(3.25,0.3) )
    slot=Loc(0,-4,0)*R2*RX1*stack(R(1.4-2*d,h),corner_r-w2+nose_len*.4,None,nose_len*.6-d,R(3.25-3*d,h))
    return slot

def nose():
    """
    This is the part that fits in a slot.
    """
    #((1.2,3), (1.2,4), (2.6,5.5))
    nose=R1*slot(0.1,nose_h)
    #nose += Loc(corner_r,0,0)*R3*RX1*extrude(base_profile,corner_r-w2-0.1)
    nose += R3*C3-Loc(w2+.1,0,0)*R2*Box(bar_w+.1,2*corner_r,bar_h,
                                        align=(Align.MIN,Align.CENTER,Align.MIN))

    nose -= Loc(0,-corner_r,0)*Box(2*corner_r,.1,bar_h,
                                   align=(Align.CENTER,Align.MIN,Align.MIN))
    nose -= Loc(0,corner_r,0)*Box(2*corner_r,.1,bar_h,
                                  align=(Align.CENTER,Align.MAX,Align.MIN))
    return nose

def slot_xy(d=0,h=slot_h):
    """
    This is the negative volume of a corner slot.
    """
    #((1.4,3),(1.4,2.2),(3.25,0.3) )
    slot=stack(R(3.5-3*d,h),
               .75*nose_len-2*d,
               R(1.4-2*d,h),
               nose_len*.3+2*d, None,
               nose_len*1.5,R(nose_len*20,bar_h*1.5))
    slot=Rot(0,0,-45)*RX1*Loc(0,0,-.8*nose_len+d)*slot
    return slot

def nose_xy(right:bool|None=None):
    """
    This is the end piece that fits in a corner slot.

    right=True/False: left/right
    right=None: both
    """
    #((1.4,3),(1.4,2.2),(3.25,0.3) )
    def rot(x):
        if right is False:
            return R2*x
        return R2*x

    # The tab
    nxy = R2*slot_xy(0.1,nose_h)

    # The part of the tab that's within the bar
    RC = C4 if right is None else (R1 if right else R2)*C3

    # the part we don't want
    bx = rot(end_cut())
    res = (RC-bx) + (bx&nxy)
    res -= Loc(0,-corner_r,0)*Box(2*corner_r,.1,bar_h,align=(Align.CENTER,Align.MIN,Align.MIN))
    res -= Loc(-corner_r,0,0)*Box(.1,2*corner_r,bar_h,align=(Align.MIN,Align.CENTER,Align.MIN))

    return res

def base(x,y):
    """
    This is your basic x*y baseplate.
    It has screw holes in the center corners and connector slots around the edge.
    """
    b=bar()
    C4S=C4-screw()
    C3S=C3-slot()
    C2S=C2-slot_xy()

    # outer corners
    p = C2S + LG(x,0)*R1*C2S + LG(x,y)*R2*C2S+LG(0,y)*R3*C2S
    # edge corners
    C3S_1=R1*C3S
    C3S_2=R2*C3S
    C3S_3=R3*C3S
    for xx in range(1,x):
        p += LG(xx,0)*C3S + LG(xx,y)*C3S_2
    for yy in range(1,y):
        p += LG(0,yy)*C3S_3 + LG(x,yy)*C3S_1
    # inner corners
    for xx in range(1,x):
        for yy in range(1,y):
            p += LG(xx,yy)*C4S

    # Bars
    for xx in range(x):
        for yy in range(y+1):
            p += LG(xx,yy)*b
    b=R1*b
    for xx in range(x+1):
        for yy in range(y):
            p += LG(xx,yy)*b
    return p

def end_cut():
    "Cutoff volume for the end of a bar that needs to fit somewhere"
    return Loc(corner_r,corner_r,0)*Cylinder(corner_r+w2+.1,
                                             bar_h,
                                             align=(Align.CENTER,Align.CENTER,Align.MIN))

def nosed_bar():
    "A bar with two standard noses."
    b=bar()
    n=nose()
    b += n + LG(1,0)*R2*n
    return b


def corner_bar(right:bool|None=None):
    """A bar with one corner and one selectable nose.
    right=None: two corner noses
    right=true/False: one standard nose
    """
    res = bar() + (R3 if right else R3 if right is None else R0)*nose_xy(right is not False)
    res += LG(1,0)*R2*(nose_xy(False) if right is None else nose())

    return res

def corner_bars():
    """A joiner for three baseplates.
    """
    res = bar()
    res += R1*res
    res += nose_xy(None)+LG(1,0)*R1*nose_xy(True)+LG(0,1)*R3*nose_xy(False)
    return res


def endboxed_square():
    """
    This is a square with four end-box corners.
    """
    res = nose_xy(None)+bar()
    res += LG(1,0)*R1*res
    res += LG(1,1)*R2*res
    return res

def zigzag_bars(right:bool=True):
    """A six-corner arragement.
    Used in place of the endboxed_square when your rows got offset by one
    due to botched planning. ;-)
    """

    b=bar()
    n=nose()
    nn=nose_xy(None)
    if right:
        b = R3*b + b + LG(1,0)*R3*b + LG(1,-1)*b + LG(2,0)*R3*b
        b += LG(0,-1)*R1*n + R3*nn +LG(1,0)*R2*nn +LG(1,-1)*R0*nn+LG(2,-1)*R1*nn+LG(2,0)*R3*n
    else:
        b = R1*b + b + LG(1,0)*R1*b + LG(1,1)*b + LG(2,0)*R1*b
        b += LG(0,1)*R3*n + R0*nn +LG(1,0)*R1*nn +LG(1,1)*R3*nn+LG(2,1)*R2*nn+LG(2,0)*R1*n
    return b

if False:
    show(LG(1,-1)*R1*nosed_bar(),"bar")
    show(base(2,1),"grid")
    show(R1*corner_bars(),"cs")
    show(R1*slot_xy(),"Slot")
#show(R3*corner_bar(None),"cs1")
#show(zigzag_bars(True),"zig")
show(bar(),"bar")
#show(nose(),"nose")
#show(endboxed_bar(True,True),"EBar")#+Rot(0,0,180)*bar(), "end")
#show(R2*corner_bar(False),"cs2")
#show(R3*corner_bar(True),"cs3")
#show(R2*corner_bars(),"cs")
#show(endboxed_square(),"sq")

os.chdir("/tmp/mk")
def make(lim=5):
    "the main thing"
    def exp(x,n):
        export_step(x,f"{n}.step")
        export_stl(x,f"{n}.stl")
    exp(corner_bar(False),"edge_left")
    exp(corner_bar(True),"edge_right")
    exp(corner_bar(None),"edge")
    exp(corner_bars(),"corner")
    exp(nosed_bar(),"side")
    exp(endboxed_square(),"center")
    exp(zigzag_bars(False),"zig_left")
    exp(zigzag_bars(True),"zig_right")
    if lim < 7:
        exp(base(7,4),"base_7_4")
    for x in range(1,lim+1):
        for y in range(1,x+1):
            b = base(x,y)
            exp(b,f"base_{x}_{y}")
make(9)
