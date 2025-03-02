from moat.d3 import *
from build123d import *
from math import sqrt

# from moat.d3.gridbox import gridbox

import sys, os
from build123d import *
from pathlib import Path
from tempfile import NamedTemporaryFile
from subprocess import run as spawn, DEVNULL

os.chdir("/src/buildscad")

if "/src/buildscad/src" not in sys.path:
    sys.path.insert(0,"/src/buildscad/src")
if "/src/buildscad" not in sys.path:
    sys.path.insert(0,"/src/buildscad")

import buildscad.main as scq



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
bar_h=8

bar_l=30



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

def LG(x,y):
    return Loc(grid*x,grid*y,0)

def RZ(x):
    return Rot(0,0,90*x)
R0=RZ(0)
R1=RZ(1)
R2=RZ(2)
R3=RZ(3)
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
    
AL=(Align.CENTER,Align.CENTER,Align.MIN)

def screw():
    """
    The hole for a screw.
    """
    if slant:
        return stack(Circle(screw_d/2),screw_h,None,(screw_head_d-screw_d)/2,Circle(screw_head_d/2),bar_h,None)
    return stack(Circle(screw_d/2),screw_h,None,Circle(screw_head_d/2),bar_h,None)

def bar():
    b=Box(bar_l,bar_w,bar_h,align=AL)
    c = Cylinder(.8,5,align=AL)
    b=b-c-Loc(125,0,0)*c-Loc(-125,0,0)*c
    for l in (10,):
        b -= Loc(-l,0,bar_h)*RX2*screw() 
    return b

d_out=2
d_in=1.8
tw=42*2-10
def drills(a,b,d1=None,d2=None):
    w=a+2*d_out
    base=RY1*stack(Rectangle(a*7,w,align=(Align.MAX,Align.MIN)),tw,Rectangle(5*a-20,w,align=(Align.MAX,Align.MIN)))
    base=chamfer(base.edges().filter_by(
        lambda e:
            abs((e@0).Y-(e@1).Y)+abs((e@0).Z-(e@1).Z)<.1 and e.center().Z<0.1).group_by(Axis.Z)[0].sort_by(Axis.Y)[0 if a>7 else -1],5)
    prev=None
    ppx = 0
    for d in range(int(a*2),int(b*2)-1,-1):
        back=(d&1)
        d /= 2
        if prev is None:
            px=d/2+d_out
        else:
            h=d+.25+d_in
            h2=d+.5+d_in
            pmin=ppx+sqrt(h2*h2+70)
            dy=w-2*d_out-(d+.5)
            dx=sqrt(h*h-dy*dy) if dy<h else 0
            ppx = px
            px = max(pmin,px+dx)
        l=50+10*d
        cyl = Loc(px,d_out+d/2 if back else w-d_out-d/2,10*back/sqrt(d)+3.5)*Cyl(d+.2,l)
        base -= cyl
        if d1 is not None:
            d1 -= cyl
            d2 -= cyl
        prev=d
    return base,d1,d2

def gridbox(nx,ny,nz):
    """
    One basic box.
    """

BS=2.5
B=R3*make_face(Polygon((0,-BS),(BS,0),(BS,BS),(-BS,BS),(-BS,0),(0,-BS),align=(None,None)))
dr1=10
dr2=6.5
dr1w=dr1+2*d_out
b_off=(dr1-dr2)/2

b1 = Loc(-3,0,10)*RY1*stack(Circle(5,2),3,None,B,10,None)
b2 = Loc(tw,0,0)*R2*b1
h1,b1,b2 = drills(dr1,dr2+.5,Loc(0,dr1w-b_off,0)*b1,Loc(0,dr1w-b_off,0)*b2)

h2,b1,b2 = drills(dr2,1, Loc(0,-dr1w,0)*b1,Loc(0,-dr1w,0)*b2)
h=Loc(0,-dr1w,0)*h1+h2-b1-b2

#show(h,"Base")
#show(b1,"S1")
#show(b2,"S2")
#box=gridbox(2,5,4)
#show_object(box,"Box")
scadf="/d/src/3d/GridFinity/openscad/gridfinity_.scad"
#scadf="/d/src/3d/Schublade/Schublade.scad"

s = scq.process(scadf)#,["examples/smooth_cubes.py"])

x,y,z = 2,2,2
#s.set_var("compartZCount",x)
#s.set_var("compartXCount",y)
#s.set_var("compartYCount",z)
breakpoint()
obj=s.mod("basic_cup",1,2,3)

