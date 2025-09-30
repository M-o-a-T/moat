/*
This file describes a board with switches which you can mount at an angle.
*/

/* [Mount plate] */
// plate thickness
bot_h=1;
// plate width
bot_d=20;

/* [Screw-down holes] */
// height of screw carrier
screw_h=1.8;
// diameter of shaft
screw_d1=4;
// diameter of head
screw_d2=7;
// diameter of carrier
screw_d3=8;
// offset screw holes from edge
screw_off=7;
// number of screws
n_screw=5; //[2:5];

/* [Panel] */
// panel thickness
side_h=1;
// distance between switches
side_w=13;
// height of panel
side_d=35;
// panel/board angle
p_angle=80; //[60:5:90]
// number of switches
n_sw=15;
// size of holes
hole_d=[6.25, 8];
// position of holes
hole_off=[12, 22];
// you can add more

/* [misc] */
// ridge between switches, for stiffness
ridge_d=1.5;
// extent of panel/board stiffening
p_carrier=12;
// chamfer angle for the top edge of the stiffeners
edge_top=80;

// cutoff at the edge
x_cut=3;

/* [hidden] */
_d=0.01;

$fn=$preview?8:48;

module screw_p() {
    cylinder(h=bot_h+screw_h, d=screw_d3);
}
module screw_n() {
    translate([0,0,-_d]) cylinder(h=bot_h+screw_h+2*_d,d=screw_d1);
    translate([0,0,bot_h]) cylinder(d1=screw_d1,d2=screw_d2,h=screw_h+_d);
    translate([0,0,bot_h+screw_h]) cylinder(d=screw_d2,h=screw_h*5);
}

module side() {
    difference() {
        translate([0,-ridge_d/2-_d,0]) cube([side_d+2*_d,side_w+ridge_d,side_h]);
        for(x=[0:len(hole_d)-1])
            translate([hole_off[x],side_w/2,-_d]) cylinder(d=hole_d[x],h=side_h+2*_d);
    }
}

module sides() {
    for(x=[0:n_sw-1])
        translate([0,side_w*x,0]) side();
    place_ridges() ridge();
}

module place_screws() {
    for(x=[0:2:n_screw-1]) {
        translate([screw_off,screw_off+x*(n_sw*side_w-2*screw_off)/(n_screw-1),0]) children();
    }
    for(x=[1:2:n_screw-1]) {
        translate([bot_d-screw_off,screw_off+x*(n_sw*side_w-2*screw_off)/(n_screw-1),0]) children();
    }
}

module ridge() {
    difference() {
        union() {
            translate([0,0,-side_h-ridge_d+_d])
            cube([side_d,ridge_d,ridge_d]);
            translate([-_d,ridge_d,-side_h-p_carrier])
                rotate([90,0,0])
                linear_extrude(ridge_d)
                polygon([[cos(p_angle)*p_carrier,(1-sin(p_angle))*p_carrier],[0,p_carrier],[p_carrier,p_carrier]]);
        }
        translate([side_d,-_d,-side_h])
            rotate([0,90+edge_top,0])
            cube([1.1*ridge_d/cos(edge_top),ridge_d+2*_d,ridge_d+2*_d]);
        translate([-_d,-_d,-side_h])
            rotate([0,p_angle,0])
            translate([0,0,-ridge_d])
            cube([1.1*ridge_d/sin(p_angle),ridge_d+2*_d,ridge_d+2*_d]);
    }
}

module place_ridges() {
    for(x=[0:1:n_sw]) {
        translate([0,-ridge_d/2+x*(n_sw*side_w)/(n_sw),bot_h]) children();
    }
}

module bottom() {
    difference() {
        union() {
            translate([0,-ridge_d/2,0]) cube([bot_d,ridge_d+side_w*n_sw,bot_h]);
            place_screws() screw_p();
        }
        translate([-_d,-ridge_d/2-_d,-side_h-ridge_d+_d]) cube([bot_d+_d,ridge_d+n_sw*side_w,side_h+ridge_d+_d]);
    }
}

module panel() {
    difference() {
        union() {
            bottom();
            translate([0,0,bot_h-_d]) rotate([0,-p_angle,0]) translate([0,0,-side_h]) sides();
            echo(p_angle/2);
            xd=(bot_h+x_cut)/cos(p_angle/2);
            translate([0*(-_d+side_h)/sin(p_angle),-ridge_d/2,0*bot_h-_d])
                rotate([-90,0,0])
                linear_extrude(ridge_d+n_sw*side_w)
                polygon([[0,0],[xd,0],[xd*cos(p_angle), -xd*sin(p_angle)]]);
        }
         place_screws() screw_n();
       rotate([0,90-p_angle/2,0])
        translate([-50,-ridge_d/2-2*_d,-_d])
        cube([100,ridge_d+n_sw*side_w+4*_d,x_cut+_d]);
    }
}

panel();
//sides();
//screw_n();
