"""
A simple bar.
"""
from __future__ import annotations

from build123d import Align, Box, Circle, Cylinder

from moat.d3 import RX2, Loc, show, stack

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
bar_w=10
# height of the bar
bar_h=25

bar_l=300



### The screw hole
# body diameter
screw_d = 3
# head diameter
screw_head_d = 5.5
# body length
screw_h = 1.5
# Is the head slanted (as in your standard wood screw)?
# False: cylinder
slant=True

def LG(x,y):
    "locate x+y"
    return Loc(grid*x,grid*y,0)

AL=(Align.CENTER,Align.CENTER,Align.MIN)

def screw():
    """
    The hole for a screw.
    """
    if slant:
        return stack(
                Circle(screw_d/2),
                screw_h, None,
                (screw_head_d-screw_d)/2,
                Circle(screw_head_d/2),
                bar_h,None)
    return stack(Circle(screw_d/2),screw_h,None,Circle(screw_head_d/2),bar_h,None)

def bar():
    "The bar itself"
    b=Box(bar_l,bar_w,bar_h,align=AL)
    c = Cylinder(.8,5,align=AL)
    b=b-c-Loc(125,0,0)*c-Loc(-125,0,0)*c
    for pos in (60,140):
        b -= Loc(pos,0,bar_h)*RX2*screw()
        b -= Loc(-pos,0,bar_h)*RX2*screw()
    return b

show(bar(),"Bar","/tmp/")
