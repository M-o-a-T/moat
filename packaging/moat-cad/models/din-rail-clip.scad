
include <e3DHW/base/lib.scad>
include <e3DHW/data/hardware.scad>
include <e3DHW/addon/base.scad>
include <e3DHW/DIN/rail.scad>
include <e3DHW/DIN/boxes.scad>

/* [Parameters] */

// top: board at x/y, side: board at y/z
mode="top"; // [side,top,top_display,rod]

// interior width. DIN units: multiples of 9 +walls!
sz_x=36; // [9:0.5:120]

// interior box height
sz_y=50; // [20:0.5:100]

// depth, DIN restriction
size_z=30; // [20:0.5:50]

// wall thickness
wall=1.5; // [0.5:0.1:3]

// space for the hook
hook_width=12; // [9:0.5:20]

// hook offset (top only)
hook_offset=0; // [-20:0.5:20]

/* [Slide-in] */

// elevation
slide_h1 = 3.5; // [0:0.5:5]
// height
slide_h2 = 2; // [0:0.5:3]
// height on top
slide_h3 = 1; // [0:0.5:3]
// corner depth
slide_d = 4; // [0:0.5:10]
// corner width
slide_w = 1.5; // [0:0.5:10]
// corner edge angle
slide_a = 45; // [0:5:45]

/* [Top] */
// wire cutout bottom
cut_h1 = 3; // [0:1:20]
// wire cutout top
cut_h2 = 5; // [0:1:20]

// top cut from left
tc_x1 = 10; // [0:0.5:50]
// top cut from right
tc_x2 = 10; // [0:0.5:50]
// top cut height
tc_h = 0; // [0:0.5:50]
// top cut slot on top
tc_s = 0; // [0:0.5:50]

/* [Rod] */
// cutout X
rc_x = 3; // [0:0.1:20]
// cutout Y
rc_y = 5; // [0:0.1:20]
// offset X
rco_x = 0; // [-20:0.5:20]
// offset Y
rco_y = 0; // [-20:0.5:20]
// nub height
rcn_h = 0; // [0:0.1:3]
// nub diameter
rcn_d = 0; // [0:0.1:5]

/* [Hidden] */
size_hook=7;

size_x=sz_x;
size_y=sz_y;

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

// box with side opening
if(mode=="side") {
din_box_side(size_y,size_z, size_x, wallThick=wall);
translate([0,size_z*2+10,0]) mirror([0,1,0])
din_box_side_lid(size_y,size_z, dw=-0.1, wallThick=wall,cut=wall);

} else if (mode=="top" || mode == "top_display") {
// box with bottom+back opening
translate([0,0,wall]) din_box_up(size_y,size_x,size_z, wallThick=wall);
if(mode == "top") {
    translate([0,size_x+10,0])
        rail_hook(hook_width, ridge=wall, slot=true);
    translate([10+size_y,size_x,size_z+2*wall])
        rotate([180,0,0])
        translate([0,0,wall])
        din_box_up_hood(size_y,size_x,size_z, wall=wall);
} else {
    color([0.4,0.8,0,0.2])
        translate([0,0,wall])
        din_box_up_hood(size_y,size_x,size_z, wall=wall);
    color([0,0.8,0.4,0.4])
        translate([-_d1,(size_x-hook_width)/2+hook_width-hook_offset,0])
        rotate([90,0,0])
        rail_hook(hook_width, ridge=wall, dw=0.12);
}

} else if (mode=="rod") {
// simple holder for a current distribution rod end
    rail_hook(hook_width, ridge=0, slot=false);

    dx1=(sz_y-rc_x)/2+rco_x;
    dy1=(size_z-rc_y)/2+rco_y;
    dx2=sz_y/2-rc_x/2-rco_x;
    dy2=size_z/2-rc_y/2-rco_y;
    dx=min(dx1,dx2);
    dy=min(dy1,dy2);

    base=(brim-spring_slot > sz_y)
        ? [[0,0],[0,spring_l],[(sz_y-rc_x)/2+rco_x-dx,size_z],[sz_y,size_z],[brim-spring_slot,0]]
        : [[0,0],[0,spring_l],[(sz_y-rc_x)/2+rco_x-dx,size_z],[sz_y,size_z],[sz_y,(size_z-rc_y)/2+rco_y-dy],[brim-spring_slot,0]]
        ;

    difference() {
        union() {

            translate([-_d1,-_d1,0])
            linear_extrude(hook_width) polygon(base);
//            cube([sz_y,size_z,sz_x]);
            translate([(sz_y-rc_x)/2+rco_x-dx, (size_z-rc_y)/2+rco_y-dy, wall])
            cube([rc_x+2*dx,rc_y+2*dy,sz_x-wall+_d2]);
        }
        translate([(sz_y-rc_x)/2+rco_x, (size_z-rc_y)/2+rco_y, wall])
        cube([rc_x,rc_y,sz_x-wall+_d2]);
    }
    translate([sz_y/2+rco_x,size_z/2-rc_y/2+rco_y,wall/2+sz_x/2]) rotate([-90,0,0]) linear_extrude(height=rcn_h,scale=0)
        circle(d=rcn_d,$fn=20);
    translate([sz_y/2+rco_x,size_z/2+rc_y/2+rco_y,wall/2+sz_x/2]) rotate([90,0,0]) linear_extrude(height=rcn_h,scale=0)
        circle(d=rcn_d,$fn=20);
}

_d=0.01;
_d1=_d; _d2=2*_d; _d3=3*_d;


module din_box_up_hood(x,y,z, wall) {
    difference() {
        union() {
            translate([-wall,-wall,z-_d])
            cube([x+2*wall,y+2*wall,wall]);

            translate([-wall,y,-wall])
            cube([x+2*wall,wall,z+wall]);

            translate([-wall,-wall,-wall])
            cube([x+2*wall,wall,z+wall]);

            translate([x-_d,0,0])
            cube([wall,y,z]);

            translate([x,0,-wall]) mirror([1,0,0]) carrier_c(slope=3,bottom=false);
            translate([x,y,-wall]) mirror([0,1,0]) mirror([1,0,0]) carrier_c(slope=3,bottom=false);
        }
        translate([_d1,0,-_d1]) din_box_up(x,y,z, dw=0.1, wallThick=wall);
        if(tc_h) {
            translate([x-wall/2,tc_x1,-_d1])
                cube([wall*2,y-tc_x2-tc_x1,tc_h]);
            echo("Z",z);
            translate([x-tc_s,tc_x1,z-wall/2])
                cube([wall*1.5+tc_s,y-tc_x2-tc_x1,wall*2]);
        }
    }
}

module latch_poly(ax, wall, dw) {
    translate([0,0,ax/3-dw])
    linear_extrude(ax/3+dw*2)
        polygon([[dw,_d],[dw,-wall*.4-dw],[-wall-3*dw,_d]]);

}

module bar_poly(ax, wall, dw) {
    translate([0,0,ax/3-dw])
    difference() {
        translate([0,0,-dw]) linear_extrude(ax/3+dw*2)
            polygon([[dw,_d],[-wall/2,wall*.4+dw],[-wall-3*dw,_d]]);
            translate([-wall,0,-dw])rotate([-30,0,0])cube([wall,wall,wall]);
        translate([-wall,0,ax/3+dw])rotate([-60,0,0])cube([wall,wall,wall]);
    }

}

module carrier_c(slope=0, wall=slide_w, top=true, bottom=true, sidetop=true) {
    zwall = wall*tan(slide_a);
    sh3=slide_h3*(1+(slope==3?tan(slide_a):0));

    if(slide_d && slide_h1) difference() {
        translate([-_d1,-_d1,-_d1]) {
            //cube([_d1,slide_d,slide_h1+slide_h2+sh3]);
            //cube([slide_d,_d1,slide_h1+slide_h2+sh3]);
            if(bottom) {
                cube([slide_d,wall,slide_h1]);
                cube([wall,slide_d,slide_h1]);
            }
            if(top) translate([0,0,slide_h1+slide_h2]) {
                if(sidetop) cube([slide_d,wall,sh3]);
                cube([wall,slide_d,sh3]);
            }
        }
        if(slope == 1) {
            // lower
            translate([_d1,_d1,slide_h1+_d1]) intersection() {
                rotate([0,90,0])
                linear_extrude(wall, convexity=10)
                polygon([[0,0],[zwall,wall],[0,wall]]);

                rotate([-90,0,0])
                linear_extrude(wall, convexity=10)
                polygon([[0,0],[wall,0],[wall,zwall]]);
            }
            translate([wall,_d1,slide_h1+_d1]) rotate([0,90,0])
            linear_extrude(slide_d-wall+_d, convexity=10)
            polygon([[0,0],[zwall,wall],[0,wall]]);

            translate([_d1,wall,slide_h1+_d1]) rotate([-90,0,0])
            linear_extrude(slide_d-wall+_d, convexity=10)
            polygon([[0,0],[wall,0],[wall,zwall]]);
        }
        if(slope == 2) {
            // upper, bottom

            translate([-_d1,-_d1,slide_h1+slide_h2-_d2]) intersection() {
                if(sidetop) translate([-_d1,0,0]) rotate([0,90,0])
                linear_extrude(wall+_d2, convexity=10)
                polygon([[0,0],[-zwall,wall],[0,wall]]);

                translate([0,-_d1,0]) rotate([-90,0,0])
                linear_extrude(wall+_d2, convexity=10)
                polygon([[0,0],[wall,0],[wall,-zwall]]);
            }
            translate([wall-_d1,0,slide_h1+slide_h2-_d2]) rotate([0,90,0])
            linear_extrude(slide_d-wall+_d2, convexity=10)
            polygon([[0,0],[-zwall,wall],[0,wall]]);

            translate([0,wall-_d1,slide_h1+slide_h2-_d2]) rotate([-90,0,0])
            linear_extrude(slide_d-wall+_d2, convexity=10)
            polygon([[0,0],[wall,0],[wall,-zwall]]);
        }
         if(slope == 3) {
            // upper, top
            sh123=slide_h1+slide_h2+sh3;
            translate([_d1,_d1,sh123+_d1]) intersection() {
                rotate([0,90,0])
                linear_extrude(wall, convexity=10)
                polygon([[0,0],[zwall,wall],[0,wall]]);

                rotate([-90,0,0])
                linear_extrude(wall, convexity=10)
                polygon([[0,0],[wall,0],[wall,zwall]]);
            }
            translate([wall,_d1,sh123+_d1]) rotate([0,90,0])
            linear_extrude(slide_d-wall+_d, convexity=10)
            polygon([[0,0],[zwall,wall],[0,wall]]);

            translate([_d1,wall,sh123+_d1]) rotate([-90,0,0])
            linear_extrude(slide_d-wall+_d, convexity=10)
            polygon([[0,0],[wall,0],[wall,zwall]]);

            if(!bottom) {
                translate([slide_d,_d1,slide_h1+slide_h2+wall/2-_d2])
                rotate([-90,0,0])
                linear_extrude(slide_w+_d2, convexity=10)
                polygon([[0,0],[-zwall/2,wall/2],[0,wall/2]]);

                translate([slide_w,slide_w,slide_h1+slide_h2+wall/2-_d2])
                rotate([-90,0,0])
                linear_extrude(slide_d-slide_w+_d2, convexity=10)
                polygon([[0,0],[-zwall/2,wall/2],[0,wall/2]]);
           }
        }
   }
}

module din_box_up(x,y,z, wallThick=1, dw=0) {
    difference() {
        translate([-wallThick,0,-wallThick]) union() {
            cube([max(37,x+wallThick)+wallThick,y,wallThick]);
            translate([0,0,0])cube([wallThick,y,z+wallThick]);

            translate([wallThick,0,0]) carrier_c(slope=2,sidetop=false);
            translate([wallThick,y,0]) mirror([0,1,0]) carrier_c(slope=2,sidetop=false);

            translate([wallThick+x,0,0]) mirror([1,0,0]) carrier_c(slope=2,top=false);
            translate([wallThick+x,y,0]) mirror([1,1,0]) carrier_c(slope=2,top=false);

            // x1
            rotate([0,90,0])
            linear_extrude(x+wallThick, convexity=20)
            polygon([[dw,_d],[-wallThick-dw,_d],[-wallThick/2,-wallThick/2-dw]]);

            // x2
            translate([0,y,0])
            rotate([0,90,0])
            linear_extrude(x+wallThick, convexity=20)
            polygon([[dw,-_d],[-wallThick-dw,-_d],[-wallThick/2,wallThick/2+dw]]);

            translate([-_d,0,z+wallThick-_d2]) rotate([-90,0,0])rotate([0,0,180])
            bar_poly(y,wallThick,dw);

        // z1
            translate([-_d1,_d2,-dw])
            rotate([0,0,180])
            bar_poly(z,wallThick,dw);

        // z2
        translate([-_d1,y-_d2,0])
            rotate([0,0,180])
            mirror([0,1,0])
            bar_poly(z,wallThick,dw);

        // at end
        intersection() {
            translate([brim-spring_slot+wall,0,0]) cube([100,100,100]);
            translate([x+wall*2,-_d1,-_d+wall])
                rotate([-90,0,0])
                mirror([0,1,0])
                bar_poly(y,wall,dw);
            }
        }
        if(dw==0)
            translate([-_d1,(y-hook_width)/2+hook_width-hook_offset,0])
            rotate([90,0,0])
            rail_hook(hook_width, ridge=wallThick, dw=0.12);

        if(cut_h1<cut_h2) {
            dh=(cut_h2-cut_h1)/1.41;
            translate([-wallThick*1.5,dh-_d2,dh+cut_h1]) rotate([135,0,0])
            cube([wallThick*2,cut_h2,cut_h2]);
        }
            // y1
    }

}

module box(x,y,z,w=1, x1=true,x2=true,y1=true,y2=true,z1=true,z2=true) {
    // Box around a volume
    if(x1) translate([-w,-w,-w]) cube([w,y+2*w,z+2*w]);
    if(y1) translate([-w,-w,-w]) cube([x+2*w,w,z+2*w]);
    if(z1) translate([-w,-w,-w]) cube([x+2*w,y+2*w,w]);
    if(x2) translate([x,-w,-w]) cube([w,y+2*w,z+2*w]);
    if(y2) translate([-w,y,-w]) cube([x+2*w,w,z+2*w]);
    if(z2) translate([-w,-w,z]) cube([x+2*w,y+2*w,w]);
}


module din_box_side(x,y, depth, wallThick=1) {
    rail_hook(size_hook,0);
    translate([brim2,0,0])
        rotate(-90)
        linear_extrude(size_hook, convexity=20)
        polygon([[0,0],[0,wallThick],[wallThick,0]]);
    difference() {
          translate([0,0,wallThick]) box(x-2*wallThick,y-2*wallThick,depth-2*wallThick, wallThick, z2=false);
//        box1(x,y,depth, lidStyle = LSNONE, bottomFill=DEFAULTFILL, boxThick=wallThick);

        wobble(_d2*5) translate([-_d1,-_d1,depth+_d1])
            mirror([0,0,1])
            din_box_side_lid(x,y,wallThick=wallThick,dw=0,dxl=5*wallThick,cut=wallThick);

        translate([-wallThick*3/2,-wallThick*3/2,depth-wallThick])
            cube([wallThick*2,wallThick*2,wallThick*2]);
        translate([-wallThick*2,y-wallThick*7/2,depth-wallThick])
            cube([wallThick*2,wallThick*3,wallThick*2]);
        translate([0,y-2*wallThick,depth-wallThick])
            rotate([0,0,45])
            cube([2*wallThick,2*wallThick,2*wallThick]);
      }
}
module din_box_side_lid(x,y, wallThick=4, dw=0,dxl=0,cut=0) {
    rail_hook(size_hook,0, cut=cut);
    difference() {
        rotate([0,180,0])
        translate([-x+wallThick+_d1,-wallThick,-wallThick])
        cube([x,y,wallThick]);

//        lid1(x,y, lidThick=wallThick, boxThick = wallThick, lidStyle = LSNONE, bottomFill=DEFAULTFILL);

        // low Y side
        translate([0,-wallThick/2-dw,wallThick/2])
        rotate([135,0,0])
        translate([brim2,-wallThick,0])
        cube([x-brim2,wallThick*2,wallThick]);

        translate([0,-wallThick/2-dw,wallThick/2])
        rotate([135+90,0,0])
        translate([brim2,-wallThick,-wallThick])
        cube([x-brim2+_d,wallThick*2,wallThick]);

        // high Y side

        difference() {
            union() {
        translate([-_d1,y-wallThick*3/2+dw,wallThick/2])
        rotate([45+180,0,0])
        translate([-_d,-wallThick/2,0])
        cube([x+_d2,wallThick*2,wallThick]);

        translate([-_d1,y-wallThick*2+dw,wallThick])
        rotate([180+135,0,0])
        translate([-_d,-wallThick/2,0])
        cube([x+_d2,wallThick*2,wallThick]);

                }
            translate([0,y-2*wallThick-dw,-wallThick/2])
            rotate([0,0,45])
            cube([2*wallThick,2*wallThick,2*wallThick]);
        }

        // high X side
        translate([x-wallThick*3/2+dw,-wallThick/2-_d1,wallThick/2])
        rotate([0,180-45,0])
        translate([-wallThick/2,0,0])
        cube([wallThick*2,y+wallThick+_d2,wallThick]);

        translate([x-wallThick*2+dw,-wallThick/2-_d1,wallThick])
        rotate([0,45,0])
        translate([-wallThick/2,0,0])
        cube([wallThick*2,y+wallThick+_d2,wallThick]);
    }
}

module wobble(x) {
    translate([-_d1,-_d1,-_d1]) children();
    translate([_d1,_d1,_d1]) children();
}

module lid1(width,height, uclip = xauto, lidHole = -7, lidThick = TOPTHICKNESS, lidFill = DEFAULTFILL, towerHole = 1, bottomFill = 100, boxThick = NOTOPTHICKNESS, lidStyle = LSIN){
      // tower size tune based on towerHole style
   _vertex = [[0,0],[width,0],[width,height],[0,height]];
    //get_DINvertex2tower(_vertex, towerHole, _dt);      // get tower positions

    translate([-boxThick,-boxThick,0])
    do_standalone_polyLid(_vertex, 1, lidAHoles =undef, lidStyle = lidStyle, lidThick = lidThick, lidFill = lidFill, sideThick = boxThick,towerAHoles = undef, round_box=boxThick);
}


module box1(width,height,depth, uclip = xauto, lidHole = -7, lidThick = TOPTHICKNESS, lidFill = 100, towerHole = 1, bottomThick = TOPTHICKNESS, bottomFill = 100, boxThick = NOTOPTHICKNESS, lidStyle = LSIN){
      // tower size tune based on towerHole style
   _towRad = get_towerRadius(towerHole, lidStyle);
   // towers borders distance
   _dt = get_towerDistance(towerHole, lidStyle);
   _vertex = (slope_h && slope_x) ? [[0,0],[width,0],[width-slope_x,height-slope_h],[width,height],[0,height]] :  [[0,0],[width,0],[width,height],[0,height]];
    _towList = undef;
    //get_DINvertex2tower(_vertex, towerHole, _dt);      // get tower positions
    translate([-boxThick,-boxThick,0])

    do_standalone_polyBox(_vertex, depth, lidAHoles =(lidHole == 0? undef:get_tower2holes(_towList, lidHole)), lidStyle = (lidStyle), lidThick = lidThick, lidFill = lidFill, bottomThick=bottomThick, bottomFill = bottomFill, sideThick = boxThick,towerAHoles = (towerHole == 0? undef: _towList),towerRadius= _towRad, round_box=boxThick);
}


module rail_hook(depth, len=0, ridge=0, dw=0, cut=0, slot=false){
    // Din-Rail - Hutschiene 35m
    aux=(len>min_len)?len-min_len:0;
    mass=depth+2*dw;
    x1=-(spring_d+spring_slot+bar_width);
    x2=dw;
    x3=dw-ridge/2;
    x5=brim-spring_slot;
    x6=brim+aux-spring_slot+dw;
    x8=brim-(spring_slot+bar_width);
    x7=brim-2-(spring_slot+bar_width);
    x10=-bar_width;
    x12=-spring_slot-bar_width;
    x14=2.5-(spring_slot+3);
    x15=2.5-(spring_d+spring_slot+bar_width);

    y1=0.5-(bar_width+hook+rail_height);
    y2=spring_l+dw;
    y4=dw+_d2;
    y5=-cut;
    y6=-(bar_width+hook+rail_height);
    y7=y6+1;
    y8=-bar_width-rail_height;
    y9=-bar_width;
    y11=spring_l-bar_width;
    y13=-rail_height-bar_width;
    y12=-rail_height-bar_width-0.2;

    rk=ridge/3;
    hsd=1; // hole slot depth
    hh=2; // height
    hw=.6; // hole's wall strength

    hd=hw+hsd;
    hws=hw*(1+sin(45));
    hdf=hws+(hd-hw);

    points=[
        [x1,y1],
        [x1,y2],
        [x3,y2],
        [x3,y4+depth/1.4+ridge*3/2],
        [x3+ridge/3,y4+depth/1.4+ridge],
        [x3,y4+depth/1.4+ridge/2],
        [x3,y4],
        [x6+cut,y4],
        [x6,y5],
        [x5,y9],
        [x5,y6+2.5],
        [x5-2.5,y6],
        [x7,y6],
        [x7,y7],
        [x8,y8],
        [x8,y9],
        [x10,y9],
        [x10,y11],
        [x12,y11],
        [x12,y13],
        [x14,y12],
        [x15,y1]

    ];
        difference() {
            union() {
                translate([0,0,-dw])
                    linear_extrude(mass+2*dw, convexity=20)
                    polygon(points);
                translate([_d2,0,0]) rotate([0,-90,0]) linear_extrude(ridge/2+dw+_d2, convexity=20)
                    polygon([[0,0],[depth,0],[depth/2,depth/1.4]]);
            if(slot)
                        intersection() {
            cube([x5,100,100]);
            translate([sz_y+wall,-_d1,hook_width/2-sz_x/2])
                bar_poly(sz_x,wall,dw);
            }

            }
            if(ridge) {
                rotate([0,90,0])
                linear_extrude(x6+_d2, convexity=20)
                    polygon([[_d1+dw,_d1-rk],[2*dw-ridge+rk,-ridge+dw],[_d1+dw,-ridge+dw]]);
                translate([0,0,mass])
                rotate([0,90,0])
                linear_extrude(x6+_d1, convexity=20)
                    polygon([[-_d1-dw,_d1-rk],[ridge-rk-2*dw,-ridge+dw],[-_d1-dw,-ridge+dw]]);

                translate([x3-ridge/2,y2-ridge/2,0])
                rotate([0,0,0])
                linear_extrude(depth+_d1, convexity=20)
                    polygon([[-dw,ridge/2+_d2+dw],[ridge/2+_d2,ridge/2+_d2+dw],[ridge/2+_d2+dw,_d1-dw]]);

                translate([x6-ridge,-ridge,0])
                linear_extrude(depth+_d1, convexity=20)
                    polygon([[rk+dw,dw],[ridge+_d2,ridge-rk-dw],[ridge+_d2,dw]]);

            }
            if(cut) {
                translate([_d1,0,+_d1])
                rotate([0,90,0])
                linear_extrude(x6+cut+_d1+ridge, convexity=20)
                    polygon([[-_d3,dw],[cut/2,cut*2/5+dw],[cut-dw,dw],[cut-dw,cut+_d3],[-_d3,cut+_d3]]);

                translate([_d1-cut,0,depth-cut+_d])
                    rotate([-90,-90,0])
                    linear_extrude(y2+cut+_d1, convexity=20)
                    polygon([[-_d3,dw],[cut/2,cut*2/5+dw],[cut-dw,dw],[cut-dw,cut+_d3],[-_d3,cut+_d3]]);

                intersection() {
                translate([-cut,-cut,depth])
                rotate([0,90,0])
                linear_extrude(cut, convexity=20)
                    polygon([[-_d3,dw],[cut/2,cut*2/5+dw],[cut-dw,dw],[cut-dw,cut+_d3],[-_d3,cut+_d3]]);

                translate([-cut,-cut,depth-cut])
                    rotate([-90,-90,0])
                    linear_extrude(cut, convexity=20)
                    polygon([[-_d3,dw],[cut/2,cut*2/5+dw],[cut-dw,dw],[cut-dw,cut+_d3],[-_d3,cut+_d3]]);
                }
            }
        }
        translate([x1,y1,0]) {
            difference() {
                hull() {
                    cube([0.01,hd+hh,mass]);
                    translate([-hd,hd,hd]) cube([0.01,hh,mass-hd*2]);
                }
                hull() {
                    translate([0,hw+0.01,hws]) cube([0.01,hd+hh-hw,mass-2*hws]);
                    translate([-hd+hw,hd+hw+0.01,hdf]) cube([0.01,hh-hw,mass-hdf*2]);
                }
            }
            translate([0,spring_l/2,0])cylinder(h=mass,d=spring_d,$fn=20);
        }
}
