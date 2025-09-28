"""
reimplementation of basic gridfinity box design by Zack Freedman
"""
# this revision is dated 2022-05-18
# designed in CadQuery and CQ-Editor both checked out from github on 2022-04-13

# Source: @jdegs
# https://www.printables.com/model/174715-basic-undivided-gridfinity-boxes-cadquery-customiz/files
# License: CC 4.0 Attribution
from __future__ import annotations

import math

import cadquery as cq


def gridbox(x_grid_number=2, y_grid_number=2, unit_height=6, disable_mholes=True):  # noqa:D103
    # adjust these three variables to change the grid size

    # box stackability is implemented!
    # boxes are always 0.5mm shy of the unit_width*42mm, and
    # that is independent of number of units

    # box interior is very minimalistic in this version

    ############################################
    # shouldn't need to adjust anything below here
    box_wd = 42.0  # mm, distance between major straight walls
    box_maj_wd = box_wd  # mm, x,y width of box to add
    box_to_box_clear = 0.5  # mm, applied only once to each x and y
    c_rad = 4  # mm, corner radius of outer box
    socket_ht = 5  # mm, overall socket height
    ov_ht = 3.8 + 7 * unit_height  # mm, overall height for a Z-unit box
    vw_ht = ov_ht - socket_ht  # mm, height of vertical walls
    wall_th = 1.0  # mm, wall thickness, don't adjust as it will break top-socket compat

    # for magnet/bolt holes
    mag_diam = 6.5  # mm
    mag_dep = 2.4  # mm
    bolt_diam = 3.0  # mm
    bolt_dep = 3.6 + mag_dep  # mm, total depth of entire hole includng 3.6mm for the bolt itself
    mag_dist0 = 26 / 2  # mm, distance from holes to zero-axis (26mm between holes total)

    bot_th = 2.0 + bolt_dep - socket_ht  # mm, bottom thickness of box interior
    # bot_th was revised to account for bolt_dep since it is longer than socket_ht
    # the revision ensures that there is 2.0mm of bottom thickness above the top of the bolt holes
    bot_fillet = 1  # mm, radius of fillet on the inside of box bottom

    # actual hypotenuse of t_chm is 3.39mm
    # actual exterior hypotenuse of t_chm is 3.04mm due to cropping

    # for socket only
    b_chm_ht = 1.13 / math.sqrt(2)  # mm, base chamfer height
    strt_ht = 1.8  # mm, straight wall height
    t_chm_ht = socket_ht - b_chm_ht - strt_ht  # top chamfer height

    # create 2D sketch with rounded corners, for the bottom of the socket
    s3a = (
        cq.Sketch()
        .rect(box_wd + 0.001, box_wd + 0.001)  # ensure boxes overlap with small add
        .vertices()
        .fillet(c_rad)
    )

    # take s3a sketch and create one socket for the bottom of box
    f2 = (
        cq.Workplane("XY")
        .placeSketch(s3a)
        .extrude(t_chm_ht * math.sqrt(2), taper=45)
        .faces(">Z")
        .wires()
        .toPending()
        .extrude(strt_ht)
        .faces(">Z")
        .wires()
        .toPending()
        .extrude(b_chm_ht * math.sqrt(2), taper=45)
        .mirror(mirrorPlane="XY")  # flip upside down
    )
    return f2

    # create sketch for exterior box walls
    box_wd_xwall = box_wd * x_grid_number - box_to_box_clear  # 0.5mm for clearance btwn boxes
    box_wd_ywall = box_wd * y_grid_number - box_to_box_clear

    s4 = cq.Sketch().rect(box_wd_xwall, box_wd_ywall).vertices().fillet(c_rad)

    # define x,y positions of the exterior walls
    wall_xpos = (box_wd) * (x_grid_number - 1) / 2
    wall_ypos = (box_wd) * (y_grid_number - 1) / 2

    # create exterior box walls
    f7 = (
        cq.Workplane("XY")
        .placeSketch(s4)
        .extrude(vw_ht)  # vertical wall height
        .translate((wall_xpos, wall_ypos, 0))
    )

    # create tool to trim off excess socket underhang
    f11 = (
        cq.Workplane("XY")
        .placeSketch(s4)
        .extrude(-socket_ht - 1)  # socket is below XY-plane
        .translate((wall_xpos, wall_ypos, 1 / 2))
    )

    c_rad_in = c_rad - wall_th  # mm, corner radius of inner box (f(wall_th))

    # create sketch for box interior that is later swept straight/chamfered
    s5 = (
        cq.Sketch()
        # should NOT be a f(wall_th) to ensure compatibility, but could create other issues
        .rect(box_wd_xwall - 2 * wall_th, box_wd_ywall - 2 * wall_th)
        .vertices()
        .fillet(c_rad_in)
    )

    # for top socket of box walls that allows stacking
    # ordered vars from lowest to highest
    wall_strt_ht1 = vw_ht - 6.5 - bot_th  # main straight interior
    wall_chm_ht1 = 2.33 / math.sqrt(2)  # 45-deg section to support socket w/o supports
    wall_strt_ht2 = 1.2
    wall_chm_ht2 = 0.98 / math.sqrt(2)
    wall_strt_ht3 = 1.8
    wall_chm_ht3 = (
        1.59 / math.sqrt(2) + 0.1
    )  # add a little extra to make sure it clears the top face

    # create tool to later subtract inside of box
    # includes fillets on the bottom interior
    # and chamfered walls that enable stacking
    f9 = (
        cq.Workplane("XY")
        .placeSketch(s5)
        .extrude(wall_strt_ht1)  # vertical wall height
        .translate((wall_xpos, wall_ypos, bot_th))  # REVISED, to make sure bot_th is correct
        .faces("<Z")
        .edges("|X or |Y")
        .fillet(bot_fillet)  # fillet bottom interior
        .faces(">Z")
        .wires()
        .toPending()
        .extrude(wall_chm_ht1 * math.sqrt(2), taper=45)  # "overhang" chamfer"
        .faces(">Z")
        .wires()
        .toPending()
        .extrude(wall_strt_ht2)  # short straight section
        .faces(">Z")
        .wires()
        .toPending()
        .extrude(wall_chm_ht2 * math.sqrt(2), taper=-45)  # 1st part of socket interface
        .faces(">Z")
        .wires()
        .toPending()
        .extrude(wall_strt_ht3)  # next short straight section for socket interface
        .faces(">Z")
        .wires()
        .toPending()
        .extrude(wall_chm_ht3 * math.sqrt(2), taper=-45)  # last part of socket interface
    )

    # pts is the locations of each grid position for each box
    # only used for socket base(s)
    pts = [
        (x * box_maj_wd, y * box_maj_wd)
        for x in range(x_grid_number)
        for y in range(y_grid_number)
    ]
    pts.pop(0)  # remove first element as not to duplicate existing socket
    f2a = f2.pushPoints(pts).eachpoint(
        lambda loc: f2.val().moved(loc),
        combine="a",
    )  # join all sockets
    f4 = f11.intersect(f2a)  # trim excess socket overhang, approx 0.25mm all sides
    f3 = f7.union(f4)  # join trimmed sockets with walls
    f8 = f3.cut(f9)  # remove box interior

    # hole_pts is center locations of ALL the magnet/bolt holes
    # BEWARE that the coordinate system is inverted in the y-direction hence the -1*
    # this is why you should not use cboreHole, because it cant do inverted holes!
    # "counterbore" all the magnet/bolt hole locations
    if not disable_mholes:
        hole_pts = [
            (
                (x * box_maj_wd - mag_dist0 * (1 - 2 * i)),
                -1 * (y * box_maj_wd - mag_dist0 * (1 - 2 * j)),
            )
            for x in range(x_grid_number)
            for y in range(y_grid_number)
            for i in [0, 1]
            for j in [0, 1]
        ]

        f8 = (
            f8.faces("<Z")
            .workplane()
            .pushPoints(hole_pts)
            .cboreHole(bolt_diam, mag_diam, mag_dep, depth=bolt_dep)
        )

    return f8
