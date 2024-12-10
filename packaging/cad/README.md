# MoaT 3D

This folder contains a bunch of OpenSCAD files that work for me.

## Switchboard

Just a row of holes, stable enough to screw to a shelf board or whatever.

I use it for my Raspberry Pi power supply. One large transformer instead of
ten small power supplies, plus switches.

You can parameterize the hell out of this.

A 3D-printed model is more stable if you set `x_cut` to a few millimeters.
Print the model with that cut-off edge facing down. (Tell the slicer to add
a brim for stability.)

## Corner box

This is a three-sided pyramid. Three faces are rectangular to each other
and interlock with strong hooks, and the fourth can be clipped on top,
closing off the box.

The model works as an enclosure, designed to occupy one corner of a room.
The three edges may be sized independently, though for esthetics a
symmetric approach is preferable (i.e. the two horizontal dimensions should
be equal).

Besides sizing and wall thinkness, you can parametrize the number and
placement of mounting holes. You can also change how much to cut off the
edges, so that the box will fit into a corner whose edges are somewhat
rounded. The hooks that connect the sides to each other have a couple of
parameters; the ridges which the hooks hold onto are auto-generated
accordingly.

The box is designed to self-lock. However, as PLA is somewhat brittle,
each corner can be secured by a screw.

There's no parameter for a inserting a cable, openings for sensors, or
attachments to mount a PCB; these can be added easily.

The prints have been tested with PLA and PETG. If you want to paint the
lid, print it with PLA and use the screws to hold it; otherwise printing
the lid with PETG and using the hooks works.
