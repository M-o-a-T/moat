"""
A single-page feeder extension for my Brother printer
"""
from __future__ import annotations

from math import atan, tan

from build123d import (
    Align,
    Axis,
    Box,
    BuildLine,
    BuildSketch,
    Plane,
    extrude,
    fillet,
    make_face,
    mirror,
)

from moat.d3 import RX1, RY3, Loc, Rot, li, lto, pos, show

ACM=(Align.CENTER,Align.CENTER,Align.MIN)

slot_x=289
slot_y=11
slot_z=43
angle=atan(15,38)
total_z=150
paper_w=211  # width of A4 paper, plus some minimal wiggle room

inset_r=19
inset_l=39
edge_x=6
edge_y=1

wall=3
guide=1
guide_x=6
guide_y=6

hold_x=6
hold_z=50
hold_y=6

slot_yt = slot_y+3

offset=(inset_l-inset_r)/2
with BuildSketch() as frame:
    with BuildLine() as lines:
        pos(0, 0)
        lto(x=slot_x/2+wall)
        lto(y=slot_y+2*wall)
        li(x=-wall-inset_r)
        li(y=-wall)
        li(x=inset_r)
        li(y=-slot_y)
        li(x=-slot_x)
        li(y=slot_y)
        li(x=inset_l)
        li(y=wall)
        li(x=-inset_l-wall)
        li(y=-2*wall-slot_y)
        lto(0,0)

    make_face()

frame=extrude(frame,slot_z)
frame=fillet(frame.edges().filter_by(Axis.Z)
             .filter_by(lambda p:abs((p@0).X) != slot_x/2  and (p@0).Y > 0),
             wall/2.5)
frame -= Rot(angle,0,0)*Box(2*slot_x,2*slot_y,2*slot_z,
                            align=(Align.CENTER,Align.MIN,Align.MAX))

with BuildSketch(Plane.YZ) as gbar:
    with BuildLine() as lines:
        pos(0, 0)
        li(hold_y,0)
        li(-hold_z*tan(angle),-hold_z)
        li(-hold_y,0)
        lto(0,0)
    make_face()

gbar=RY3*extrude(gbar,hold_x)
gbar=fillet(gbar.edges().filter_by(Axis.X).group_by(Axis.Y)[0],min(hold_y,hold_z)/5)

frame += Loc(hold_x/2,0,0)*gbar + Loc(slot_x/2-wall+hold_x,0,0)*gbar + Loc(-slot_x/2+wall,0,0)*gbar

# subtract guides
gd = Box(edge_x,edge_y,slot_z, align=(Align.MIN,Align.MIN,Align.MIN))
frame -= Loc(slot_x/2-edge_x,wall+slot_y,0)*gd + Loc(-slot_x/2,wall+slot_y,0)*gd

# shift it over
frame = Loc((inset_r-inset_l)/2,-wall-slot_yt,-slot_z)*frame

with BuildSketch(Plane.YZ) as pbar:
    with BuildLine() as lines:
        pos(0, 0)
        li(total_z,0)
        li(0,-wall)
        lto(0,-wall-slot_yt)
        lto(0,0)
    make_face()

pbar = RY3*extrude(pbar,guide_x)

frame += (Loc(guide_x/2,0,0)*pbar
          +Loc(guide_x/2+paper_w/4,0,0)*pbar
          +Loc(guide_x/2+paper_w/2,0,0)*pbar
          +Loc(guide_x/2-paper_w/4,0,0)*pbar
          +Loc(guide_x/2-paper_w/2,0,0)*pbar
          )

side=Box(guide_x/2,guide_y,total_z,align=(Align.MIN,Align.MIN,Align.MIN))
frame += Loc(paper_w/2,0,0)*side + Loc(-paper_w/2-guide_x/2,0,0)*side

with BuildSketch(Plane.XZ) as stab:
    with BuildLine() as lines:
        pos(guide_x/2, 0)
        li(-guide_x,0)
        li(0,guide_x)
        li(paper_w/4,total_z*2/3)
        li(guide_x,0)
        li(0,-guide_x)
        lto(guide_x/2, 0)
    make_face()
stab=RX1*extrude(stab,wall)
#stab += Loc(paper_w/8,0,total_z/3+guide_x/2)*RX3*Cyl(guide_x/2,3)
stab=Loc(0,-slot_yt,0)*Rot(atan(-slot_yt,total_z),0,0)*stab

frame += stab +Loc(paper_w/4,0,0)*stab+Loc(-paper_w/4,0,0)*stab+Loc(-paper_w/2,0,0)*stab
stab=mirror(stab,Plane.YZ)
frame += stab +Loc(paper_w/4,0,0)*stab+Loc(-paper_w/4,0,0)*stab+Loc(paper_w/2,0,0)*stab

d=slot_x-paper_w-inset_r-inset_l
with BuildSketch(Plane.XZ) as tri:
    with BuildLine() as lines:
        pos(0, 0)
        lto(d,0)
        lto(0,2*d)
        lto(0, 0)
    make_face()
tri=Loc(paper_w/2,wall+slot_y-slot_yt,0)*RX1*extrude(tri,wall)
frame += tri + mirror(tri,Plane.YZ)

show(frame,"Result","/tmp/")
