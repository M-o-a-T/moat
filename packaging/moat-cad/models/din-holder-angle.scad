/* Params */
// wall thickness
wall=1.5; // [0.5:0.1:3]
// on-top rail length
rail_length=25; // [15:1:40]
// hook size
hook_strength=8; // [5:1:20]
// delta between base and inset
spacing=0.05; // [-0.2:0.05:0.2]
// hook offset
hook_off=2; // [0:0.5:5]


/* [Hidden] */

// DIN rail
brim=35.1;
rail_height=1.1;

// DIN rail hook
spring_l=15;
spring_d=2.5;
spring_slot=0.9;
bar_width=max(2.5,wall);
hook=4;
min_len=brim+bar_width*2+spring_slot;
brim2=brim-spring_slot;

include </src/moat-3d/lib/din-rail-hook.scad>

_d=0.01;
_d1=_d; _d2=2*_d; _d3=3*_d;

rail_depth=4;


difference() {

translate([_d1,0,_d1-wall]) {
    translate([0,-rail_length,0])
        cube([brim,rail_length,wall*2.5+hook_off]);
//    polygon([[0,-rail_length],[0,0],[brim,0],[brim,-rail_length]]);

translate([0,-rail_length,hook_off])
    din_rail_hook(hook_strength);
}
translate([0,-rail_length-_d,-rail_depth]) rotate([0,-90,-90])
rail(rail_length+_d2, dy=rail_depth,miter=1,edge=1.5,d=spacing,w2=3);
}

translate([brim-_d1,_d1-rail_length,wall*1.5+hook_off-_d1]) rotate([0,-90,0]) linear_extrude(brim+_d2) polygon([[0,0],[0,wall*2],[wall*2,0]]);
//translate([brim-_d1,_d1-rail_length,wall*1.5+hook_off-_d1]) rotate([0,-90,0])
#translate([0,spring_l-rail_length-_d1,wall*1.5+hook_off-_d1]) rotate([90,0,0]) linear_extrude(spring_l+_d1) polygon([[0,0],[0,wall*2],[wall*2,0]]);

translate([0,10,0]) rotate([0,0,-90])
rail(rail_length+_d2, dy=rail_depth,miter=1,edge=1.5,d=0,w2=3);

module rail(depth, dy=7.5, miter=1, edge=0, edge_p=0.75, d=0, w2=0) {
    dx=35;
    w=1.0;
    offx=5;
    ww=w2?w2:w;
    miterw=w2?miter*w/w2:miter;

    linear_extrude(depth)
    polygon([[0,0],[0,offx],[dy-ww,offx+miterw*offx],[dy-ww,dx-offx-(miterw*offx)],
        [0,dx-offx],[0,dx],[w,dx],[w,dx-offx+w+miter*(offx-2*w)],[dy-edge,dx-offx+w+d],[dy+d,dx-offx+w+edge*edge_p+d],
        [dy+d,offx-w-edge*edge_p-d],[dy-edge,offx-w-d],[w,offx-w-miter*(offx-2*w)],[w,0]]);
}
