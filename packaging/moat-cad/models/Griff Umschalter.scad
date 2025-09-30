_t=false;

h=_t?11:15;
d1=_t?15:30;
d2=_t?15:25;
rg=_t?1:3;
h_hole=10.5;
xlen=_t?10:40;

ds1=0; // 3; // screw hole 1
ds2=5; // screw hole inset diameter

d_m=12.4;
d_c=5.9;
d_d=5;
d_h=8;

sx=1.75;
sxe=6.2;
d_corner=3.4;
d_edge=4.7;

_d=0.01;

module griff() {
difference() {
    hull() {
        cylinder(d1=d1,h=0.1);
        translate([0,0,h-rg]) rotate_extrude() translate([d2/2-rg,0]) circle(r=rg, $fn=32);
        //translate([30,0,h/2]) cube([h,h,h], center=true);
        if(!_t) {
        translate([xlen,h/2-(d1-d2)/3,h-rg]) sphere(r=rg);
        translate([xlen,-h/2+(d1-d2)/3,h-rg]) sphere(r=rg);
        translate([xlen+(d1-d2)/2,h/2,0]) linear_extrude(0.01) circle(r=rg);
        translate([xlen+(d1-d2)/2,-h/2,0]) linear_extrude(0.01) circle(r=rg);
        }
    }
    translate([0,0,-0.001]) hole();
}
}
griff();
if(_t)
translate([0,20,0]) intersection() {
    griff();
    cube([d_c+0.5,d_c+0.5,22], center=true);
}

module hole() {
        module edge() {
            // cylinder(h=22,d=2,center=true,$fn=16);
            cube([sx,sx,22], center=true);
        }
    difference() {
        cylinder(h=h_hole,d=d_m);
        difference() {
            cube([d_c,d_c,22], center=true);
            rotate(45) translate([-5-d_corner,0,0]) cube([10,10,22], center=true);
        }
        translate([-10-d_edge,0,0]) cube([20,20,30],center=true);
        translate([sxe,0,0]) edge();
        translate([0,-sxe,0]) rotate(90) edge();
        translate([0,sxe,0]) rotate(-90) edge();
    }

    if(ds1) {
    translate([0,0,d_h/2]) rotate([0,-90,0]) cylinder(h=d1/2,d=ds1,$fn=5);
    translate([d1/2-d2,0,d_h/2]) rotate([0,-90,0]) cylinder(h=d1/2,d=ds2);
    }

}
