/* [Sizes] */
// size X
x=49;
// size Y
y=28;
// size Z
z=24;
// plus wall
w=2.0;//[1:0.2:5]

/* [Holes] */
// left
h1=true;
// right
h2=true;
// front
h3=true;
// top
h4=true;

// hole width
cw=13;
// top hole width
ch=6;
// upper edge
chh=12;
// lower edge
chl=6;
// side offset
cso=0;
// additional right side hole width
cswr=0;

/* [Hidden] */
_d1=0.01;
_d2=0.02;
_d3=0.03;

module indent(c) {
    hull() {
        translate([w/2,0,w/3]) cube([_d1,c-w/3,_d1]);
        translate([-_d1,0,0]) cube([w,c,_d1]);
    }
}

module bottom() {
   hull() {
        translate([-w,0,0]) cube([x+w,y,_d1]);
        translate([-w,w,-w]) cube([x,y-2*w,_d1]);
    }
    translate([-w,-w,-w]) cube([x/2+cw/2+w+cso,y+2*w,w]);
    translate([_d1-w,0,-_d1]) cube([w,y,z]);
    translate([_d1-w,-w,-w]) cube([w,y+2*w,w+chh]);
    #translate([-w,-w,-w]) cube([x/2-cw/2+w+cso-cswr,w,w+chh]);
    translate([-w,y,-w]) cube([x/2-cw/2+w+cso,w,w+chh]);
    // lowers
    if(h3) {
        translate([x,y/2-cw/2,-w]) cube([w,cw,chl+w]);
        translate([x-w+_d1,y/2-cw/2,-w]) cube([w+_d2,cw,w]);
    }
    translate([x/2-cw/2-_d1+cso-cswr,-w,-_d1]) cube([cw+cswr,w,h2?chl:chh]);
    translate([x/2-cw/2-_d1+cso,y,-_d1]) cube([cw,w,h1?chl:chh]);
    // align sliders on top
    translate([-_d1,0,z]) rotate([-90,0,0]) linear_extrude(y/2-cw/2) polygon([[0,0],[0,w],[w,0]]);
    translate([-_d1,y/2+cw/2,z]) rotate([-90,0,0]) linear_extrude(y/2-cw/2) polygon([[0,0],[0,w],[w,0]]);
    // indents on side
    translate([-w,0,chh]) rotate([90,0,0]) indent((z-chh)/2);
    translate([0,y,chh]) rotate([90,0,180]) indent((z-chh)/2);

}
module side_top() {
    rotate([90,0,0]) linear_extrude(w) polygon([
        // top and right sides
        [-w,z+w], [x+w,z+w], [x+w,-w],
        // hole
        [x/2+cw/2+cso,-w], [x/2+cw/2+cso,chh], [-w,chh],
    ]);
}
module _top() {
    // top
    translate([-w,0,z]) cube([x+2*w,y,w]);
    // front
    translate([x,0,-w]) cube([w,y,z+2*w]);
    translate([x-w+_d1,0,0]) rotate([-90,0,0]) linear_extrude(y) polygon([[w,w],[0,w],[w,0]]);
    // left
    //translate([-w,_d1-w,-w]) cube([x+2*w,w,z+2*w]);
    translate([0,_d1,0]) side_top();
    translate([x/2+cw/2+cso,-_d1,-w]) rotate([0,90,0]) linear_extrude(x/2-cw/2-cso+w+_d1) polygon([[0,0],[0,w],[-w,0]]);
    translate([x/2+cw/2+cso,-_d1,w/4]) rotate([0,90,0]) linear_extrude(x/2-cw/2+w-cso+_d1) polygon([[0,0],[0,w],[-w,0]]);
    // right
    translate([0,y+w-_d1,0]) side_top();
    translate([x/2+cw/2+cso,y+_d1,-w]) rotate([0,90,0]) linear_extrude(x/2-cw/2-cso+w+_d1) polygon([[0,0],[0,-w],[-w,0]]);
    translate([x/2+cw/2+cso,y+_d1,w/4]) rotate([0,90,0]) linear_extrude(x/2-cw/2-cso+w+_d1) polygon([[0,0],[0,-w],[-w,0]]);
    // guides at top
    translate([-_d1+w/4,0,z+_d1]) rotate([-90,0,0]) linear_extrude(y/2-cw/2) polygon([[2*w,0],[2*w,w],[0,w],[w,0]]);
    translate([-_d1+w/4,y/2+cw/2,z+_d1]) rotate([-90,0,0]) linear_extrude(y/2-cw/2) polygon([[2*w,0],[2*w,w],[0,w],[w,0]]);
}
module top() {
    difference() {
        _top();
        // cable on top
        if(h4) translate([-w-_d1,y/2-cw/2,z-w/2]) cube([ch+w,cw,2*w]);
        // cable on front
        if(h3) translate([x-1.5*w,y/2-cw/2,-w-_d1]) cube([3*w,cw,chh+w]);
        // indents on side
        translate([-w,_d2,chh-_d2]) rotate([90,0,0]) indent((z-chh)/2);
        translate([0,y-_d2,chh-_d2]) rotate([90,0,180]) indent((z-chh)/2);
        // cut odd top and bottom a bit
        translate([-w-_d1,-w-_d1,-w-_d1]) cube([x+2*w+_d3,y+2*w+_d3,w/4]);
    }
}

//difference() { union() {
bottom();
if($preview) color([0,1,0,.3]) top();
translate([-x-5*w,y,z]) rotate([180,0,0]) top();
//}translate([-8*w-x,-2*w,-2*w]) cube([2*x+10*w,y/2+2*w,z+4*w]);}
