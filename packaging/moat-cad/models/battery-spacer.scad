// cell diameter
cell_d=33; // [5:0.5:50]

// cell height
cell_h=72; // [5:0.5:100]

// extra space between cells
spacer=1; // [ 0.4:0.2:5]

// ring width
ring_w=2; // [0.4:0.2:5]

// height of ring edge
ring_h=3; // [0.4:0.2:10]

// bottom?
ring_b=1; // [0.4:0.2:10]

// tap width
tap_w=5; // [1:0.5:20]

// tap depth
tap_d=0.6; // [0:0.2:10]

// tap circle
tap_c=10; // [5:1:45]

// #cells
num=3; // [1:99]

// open at start?
open=false;

/* [Hidden] */
_d=0.01;

module batt_p(rot=false) {
    cylinder(h=ring_h+ring_b, d=cell_d+ring_w*2);
    rotate(rot?180:0) translate([0,-(tap_w+2*ring_w)/2,0]) cube([cell_d/2+spacer/2+_d,tap_w+2*ring_w,ring_h+ring_b],center=false);
}
module batt_n(rot=false) {
    translate([0,0,ring_b]) cylinder(h=ring_h+_d,d=cell_d);
    rotate(rot?180:0) translate([0,-(tap_w)/2,ring_b-tap_d-_d]) cube([cell_d/2+spacer*2+_d,tap_w,ring_h+tap_d+2*_d],center=false);
    translate([0,0,ring_b-tap_d-_d]) cylinder(h=ring_h+ring_b,d=tap_c);
}

module arr_p() {
    for(x=[0:num-1]) {
        translate([x*(cell_d+spacer),0,0]) batt_p(!(x%2)==open);
    }
}
module arr_n() {
    for(x=[0:num-1]) {
        translate([x*(cell_d+spacer),0,0]) batt_n(!(x%2)==open);
    }
}
module holder() {
    difference() {
        arr_p();
        arr_n();
    }
}
holder();
