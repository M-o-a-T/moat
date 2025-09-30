// This file generates a minimal frame for a Raspberry Pi,
// optionally with a LiFePo4wered battery. Or whatever.
//

/* [Frame] */
// height of frame
h_f=2.5;
// width of frame
w_f=4.5;
// squeeze factor for better roundness
edge_r=0.7;
// additional roundness at the edges (distance the edges stay away from the center of the corner).
edge_d=1.3;
// Top edge recess
edge_f=0.7;

/* [Pi] */
// how many?
n_pi=1; //[1:20]
// X size
pi_x=85.5; // [10:0.2:100]
// Y size
pi_y=56.0; //[10:0.2:100]
// Highest thing on top
pi_z=17; //[3:0.2:50]

// highest thing on bottom
pi_bottom=2.5;
// thickness of circuit board
board_z=1.5;
// peg diameter, less .25mm or so
d_h=2.5;
// reduced diameter on top of cone
d_hx=0.3;
// additional space in hollow parts
d_d=0.7;

/* [Holes] */
// distance from top edge
dh_top = 3.7; //[1:0.2:30]
// distance from left edge
dh_left = 3.7; //[1:0.2:30]
// distance from bottom edge
dh_bottom = 23.7; //[1:0.2:30]
// distance from right edge
dh_right = 3.7; //[1:0.2:30]

/* [HoleArrangement] */
// center bottom hole?
dh_center_bot=false;
// ignore top-left hole?
dh_hide_tl=false;
// ignore top-right hole?
dh_hide_tr=false;
// ignore bottom-left hole?
dh_hide_bl=false;
// ignore bottom-right hole?
dh_hide_br=false;

/* [Clamps] */
// add clamps?
with_clamp=false;
// clamps on top? (No holes if not)
cl_top=false;
// Clamp offset
cl_offset=5; // [2:0.5:50]
// Clamp width
cl_width=5; // [2:0.5:20]
// clamp additional height
cl_height=2; // [1:0.5:3]
// clamp intrusion bottom
cl_depth=2; // [1:0.5:3]
// clamp intrusion top
cl_depth_top=1; // [0.6:0.2:3]
// thickness of top circuit board, if cl_top
board_z2=1.5;


cl_skip_x1a=false;
cl_skip_x1b=false;
cl_skip_x2a=false;
cl_skip_x2b=false;
cl_skip_y1a=false;
cl_skip_y1b=false;
cl_skip_y2a=false;
cl_skip_y2b=false;

/* [Battery] */
// add a battery to the side?
with_bat=true;
// battery width.
bat_y=21.5;
// distance bottom of battery to bottom of circuit board
bat_z=6.8;
// distance between pi and battery boards
bat_d=11.1;
// free space in top right corner
bat_spc=9.5;
// shift for stiffener
bat_off=6;

/* [DIN rail] */
// print rail holder
on_rail=true;
// attach rail holder
attached_rail=true;
// mirror attached rail holder?
attached_mirrored=false;
// Flat design?
upright_rail=true;
// X side?
rail_short=false;
// opposite side?
rail_opp=false;
// rail hook width
rail_hook_w=2.0; //[0.5:0.1:4]
// hook 1: half circle plus
rail_deg_a=10; //[-135:45]
// hook 2: half circle plus
rail_deg_b=10; //[-180:45]
// width of rail bar if upright
rail_width=15; //[8:1:20]
// offset for guides for upright rail inserts
rail_delta=0.1; // [-0.2:0.05:0.2]
// Outset for left side
rail_up_out_l=0; // [0:1:20]
// Outset for right side
rail_up_out_r=0; // [0:1:20]
// slot slaling
rail_up_scale=0.5; // [0.1:0.1:1]

/* [Hidden] */
bat_y_=with_bat?bat_y:0;
bat_z_=max((with_bat?bat_z:0),pi_bottom+h_f);

edge_top=w_f*edge_f; // top edge set-in for the bottom's pegs to hook into
edge_xtop=w_f*(edge_f/2+0.5);
h_ppin=1; // additional pin length on top
m_x1=dh_top;
m_x2=pi_x-dh_bottom;
m_y1=dh_left;
m_y2=pi_y-dh_right; // pos of mount holes
fr_side=w_f/2+1; // additional offset for the frame
ext=fr_side+w_f/2; // total extent outside of board

c_w = h_f*edge_r/2;
_d=0.01;_d1=_d;_d2=_d*2;

d_hb=max(d_h+1,min(w_f,5)); // pegs at their base

bat_x1=m_x1;
bat_x2=m_x2;
bat_y2=m_y2;
bat_y1=bat_y2-22.5;

rail_d=(rail_short?pi_y:pi_x)+2*fr_side+(upright_rail ? w_f : -edge_d);
// echo("RAIL",rail_d);

// upright rail poly
hfk=h_f*rail_up_scale/2;
hf2=hfk*0.2;
hf3=hfk;

// Pin height
board_zp = (with_clamp && cl_top) ? board_z+0.2 : board_z*2;

// offset of the straight part of the edge to its center
edge_dx=w_f/2-h_f*edge_r/2;

// same but adjusted by corner roundness requirements
edge_dm=min(edge_d, edge_dx);

h_total=pi_z+board_z+bat_z_+board_z;
bat_top=h_total-(bat_z_+board_z*2+bat_d);
pib_y=pi_y+bat_y_+fr_side;
// echo("HT",h_total,pi_z,bat_z_,h_f,bat_top);

// translate([pi_x,pi_y*n_pi,0]) rotate(180)
if(on_rail && upright_rail)
rail_bottom();
else bottom();

mx=max(rail_up_out_l,rail_up_out_r);

//top();
if($preview) translate([pi_x,0,h_total]) rotate([0,180,0]) top();
else translate([pi_x+4*fr_side+mx,0,0]) top();
// translate([-bat_x1,-bat_y2+d_h/2,0])
//{ bottom(); flip_top() top(); }
if(on_rail) {
    if (upright_rail) {
        translate([-5-fr_side-mx,-5-fr_side-hfk*2-mx,0]) mpcarrier();
        translate([-5-fr_side-hfk*2-mx,5+pib_y,0]) rotate([0,0,-90]) mpcarrier();
    } else {
        translate(attached_rail ? [-rail_d/2+22,-w_f*1.5 ]: [-rail_d/2+17.3,-10-d_h*5 ])
        attached() carrier();
    }
}

include <e3DHW/data/hardware.scad>
include <e3DHW/DIN/rail.scad>
include <e3DHW/base/array.scad>

include <moat-3d/din-rail-hook.scad>

module attached() {
    if(!attached_rail) children();
    else if(rail_opp && rail_short) rotate(-90) children();
    else if(rail_opp) translate([2*pi_x-37,pib_y+2.5*w_f,0]) rotate(180) children();
    else if(rail_short) rotate(90) children();
    else children();
}

module mcarrier() {
    din_rail_hook(rail_width, len=rail_brim+hfk*2+hf2);
}

module mpcarrier() {
    mcarrier();
    translate([-_d,-_d,0]) rotate([0,180,0])     rotate([180,90,-90]) rail_poly();
}

module rail_bottom(d=0) {

    difference() {
        union() {
            bottom();
            rail_pos() cube([rail_width,rail_brim,h_f]);
        }
        rail_pos() rail_poly(rail_delta);
    }
}
module rail_poly(d=0) {
    translate([-_d,-_d,hfk]) rotate([0,90,0]) rotate([0,0,90]) linear_extrude(rail_width+_d2)
                polygon([[0,-hfk-d],[0,hfk+d],[hfk+d,0]]);

    translate([-_d,rail_brim+_d,hfk]) rotate([0,90,0]) rotate([0,0,-90]) linear_extrude(rail_width+_d2)
                polygon([[-hf2,-hf2-hfk-d],[-hfk*2-hf2*1.41,hfk],[0,hfk+d],[hfk+d,0]]);
}

module rail_pos() {
    if(rail_short) {
        if(rail_opp) {
            translate([pi_x+ext,pi_y+bat_y_+ext-rail_width,0]) rotate([0,0,90]) children();
            translate([pi_x+ext,-ext,0]) rotate([0,0,90]) children();
        } else {
            translate([-ext,rail_width-ext,0]) rotate([0,0,-90]) children();
            translate([-ext,pi_y+bat_y_+ext,0]) rotate([0,0,-90]) children();
        }
    } else {
        if(rail_opp) {
            translate([rail_width-ext-rail_up_out_r,pi_y+bat_y_+ext,0]) rotate([0,0,180]) children();
            translate([pi_x+ext+rail_up_out_l,pi_y+bat_y_+ext,0]) rotate([0,0,180]) children();
        } else {
            translate([-ext,-ext,0]) children();
            translate([pi_x+ext-rail_width,-ext,0]) children();
        }
    }
}

module cclip(dep,aplus=0,wh=2,maxaplus=0) {
    ri=w_f/2*1.1;
    w=attached_rail ? w_f : w_f+wh/2+sin(maxaplus)*(wh/2+ri);
    //if($preview) tran24.5slate([wh*3/2+ri*2,w_f/2,0])color("green") cylinder(h=dep,d=w_f,$fn=30);
    translate([0,-_d,0]) {
        cube([wh,w,dep]);
        if(!attached_rail) translate([ri+wh,w-_d,0]) rotate(-aplus) {
            rotate_extrude(angle=180+aplus) translate([ri,0]) square([wh,dep]);
            translate([wh/2+ri,0,0]) cylinder(h=dep,d=wh,$fn=30);
        }
    }
    if(aplus<0 && !attached_rail) {
        translate([ri+wh,w-_d,0])  {
            rotate(180) rotate_extrude(angle=-aplus,$fn=50) translate([ri,0]) square([wh,dep]);
        rotate(-aplus) translate([-wh/2-ri,0,0])
            cylinder(h=dep,d=wh,$fn=30);
        }
    }
}

module carrier() {
    dep=upright_rail ? rail_width : attached_rail ? pi_z*3/4: bat_z_+pi_z-h_f-1; // depth (z)
    c_off=rail_d/2-25.5-rail_hook_w/2;
    wh=rail_hook_w;// 3/2*d_h;
    maxa=max(rail_deg_a,rail_deg_b);
    echo("D",dep, rail_d,wh, c_off);
    if(attached_mirrored) {
        translate([rail_d*1.5-fr_side-1,0,0]) mirror([1,0,0]) do_DINClip("SPF", dep, rail_d+wh, off=c_off);
    } else
    do_DINClip("SPF", dep, rail_d+wh, off=c_off);
    if(!upright_rail) {
        translate([c_off,0,0]) cclip(dep,rail_deg_a,wh,maxa);
        translate([rail_d+c_off,0,0]) cclip(dep,rail_deg_b,wh,maxa);
}
}

module flip_top() {
    translate([pi_x,0,h_total]) rotate([0,180,0]) children();
}

module edge_c() {
    // the profile of the side of a line
    linear_extrude(_d,center=true)
        scale([edge_r,1])
        circle(d=h_f,$fn=12);
}

module f_base() {
    // the corner roundness
    d = w_f/2-c_w;
    translate([edge_dm,edge_dm,h_f/2]) hull() rotate(-45) rotate_extrude(angle=180,$fn=16) translate([-d-edge_dm,0]) difference() {
        scale([edge_r,1]) circle(d=h_f,$fn=12);
        translate([0,-w_f/2]) square([h_f,w_f]);
    }
}

module f_base_top() {
    // The inset at the corners, trimmed for good interlock
    em=edge_dm+edge_top;

    dd = edge_dm;//h_f*edge_r/2;
    //dd = w_f/2-c_w;
    a=45;
    ed=dd*(1-1*cos(a));
    eds=dd*sin(a);

    module ci() { // corner insert
        translate([edge_dm,0,h_f/2]) rotate_extrude(angle=45,$fn=48)
        difference() {
                translate([-edge_dm,0]) union() {
                    translate([-edge_dx,-h_f/2]) square([edge_dx*2,h_f]);

                    translate([-edge_dx,0]) scale([edge_r,1]) circle(d=h_f,$fn=12);
                    translate([edge_dx,0]) scale([edge_r,1]) circle(d=h_f,$fn=12);
                }
                translate([0,-w_f/2]) square([h_f,w_f]);
            }
    }

    d = w_f/2-c_w;
    difference() {
        union() {
            translate([0,em,0]) ci();
            translate([em,0,0]) rotate(90) mirror([0,1,0]) ci();
            line(em+_d-eds, ed-_d,ed-_d, em-eds-_d);
        }
        translate([0,0,-_d1]) _pin(d=edge_xtop,h=h_f+_d2);
    }
}
//!f_base_top();

module f_base_top_i() {
    // the inset at the sides, for multi-device frames
    em=edge_dm+edge_top;
    dd = h_f*edge_r/2;//w_f/2-c_w;
    ed=dd*sin(22.5);
    eds=dd*cos(22.5);
    module ci(n=0) {
        translate([0,0,h_f/2])
        rotate_extrude(angle=45*(n+1),$fn=48)
        // basic wedge, c_w+edge_dm
        translate([-d-edge_dm-n*(c_w+edge_dm/2),0])
        union() {
            translate([0,-h_f/2]) square([edge_dm*2,h_f]);
            difference() {
                // half ellipse
                scale([edge_r,1]) circle(d=h_f,$fn=12);
                translate([0,-w_f/2]) square([h_f,w_f]);
            }
        }
    }
    d = w_f/2-c_w;
    difference() {
        union() {
            translate([-edge_top-edge_dm,edge_dm,0]) rotate(90)ci();
            translate([edge_top+edge_dm,edge_dm,0]) rotate(45) ci();
            line(em-eds+_d,ed-_d,(em-eds+ed)/2,(em-eds+ed)/2);
            line(eds-em-_d,ed-_d,(eds-em-ed)/2,(em-eds+ed)/2);
            rotate(180+45)ci(1);
        }
        translate([0,0,-_d1])_pin(d=edge_xtop,h=h_f+_d2);
    }
}

module f_end() {
    // the profile of a line
    d = w_f/2-c_w;
    translate([0,0,h_f/2]) rotate([90,0,0]) hull() {
        translate([-d,0,0]) edge_c();
        translate([ d,0,0]) edge_c();
    }
}

function eqd(a,b) = (a==b)?1:-1;

module line(x1,y1,x2,y2) {
    // a simple line. No end caps.
    //translate([x1,y1,0]) rotate(atan2(y2-y1,x2-x1))
    //cube([norm([y2-y1,x2-x1]),_d,_d]);
    a=90+atan2(y2-y1,x2-x1);
    hull() {
        translate([x1,y1,0]) rotate(a) f_end();
        translate([x2,y2,0]) rotate(a) f_end();
    }
}
// !line(0,0,100,0);
// Draw a 45° line through px/py that ends at tx and ty coordinates.
module xline(px,py, tx,ty) {
    dx=(px-tx)*eqd(px>tx, py>ty);
    dy=(py-ty)*eqd(px>tx, py>ty);
    line(tx,py+dx,px+dy,ty);
}
module frame(top=false) {
    ed=top?edge_dm+edge_top-_d:edge_dm-_d;
    line(    -fr_side+ed,    -fr_side, pi_x+fr_side-ed,-fr_side);
    if(top) {
        for(x=[0:n_pi-1]) {
            line(pi_x+fr_side,    -fr_side+ed+(x?fr_side+x*pi_y:0), pi_x+fr_side, pib_y-ed-fr_side+x*pi_y+((x==n_pi-1)?fr_side:0));
            line(    -fr_side,    -fr_side+ed+(x?fr_side+x*pi_y:0), -fr_side, pib_y-ed-fr_side+x*pi_y+((x==n_pi-1)?fr_side:0));
        }
    } else {
        line(pi_x+fr_side,pib_y-ed+(n_pi-1)*pi_y, pi_x+fr_side,-fr_side+ed);
        line(    -fr_side,    -fr_side+ed, -fr_side,pib_y-ed+(n_pi-1)*pi_y);
    }
    line(pi_x+fr_side-ed,pib_y+(n_pi-1)*pi_y, -fr_side+ed,pib_y+(n_pi-1)*pi_y);
    if(n_pi>1) for(x=[1:n_pi-1])
        if(top) {
            line(pi_x,x*pi_y,0,x*pi_y);
        } else {
            line(pi_x+fr_side,x*pi_y, -fr_side,x*pi_y);
        }
    if(with_bat) {
        n=min(pi_x,pi_y)/4;
        if(top) {
            line(m_x1,-fr_side,m_x1,pi_y+fr_side);
            line(m_x2,-fr_side,m_x2,pib_y);
            xline(m_x2+1,pib_y-1,pi_x+fr_side,pib_y);
            xline(m_x1, pi_y+fr_side, -fr_side,pib_y);
            xline(m_x2-1,m_y2+bat_off,m_x2,pib_y);
        } else {
            xline(0,pi_y-n, -fr_side,m_y2);
            xline(pi_x,pi_y-n, pi_x+fr_side,m_y2);
            line(-fr_side,m_y2, pi_x+fr_side,m_y2);
            d=w_f*1.5;
            xline(pi_x-bat_spc/2,pib_y-bat_spc/2,pi_x+fr_side,pib_y);
            //xline(bat_spc/2,pib_y-bat_spc/2,-fr_side,pib_y);
        }
    } else {
        if(!dh_hide_tr) xline(m_x1,m_y2+(n_pi-1)*pi_y,    -fr_side,pi_y+fr_side+(n_pi-1)*pi_y);
        if(!dh_hide_br) xline(m_x2,(dh_center_bot&&dh_hide_bl?pi_y/2:m_y2)+(n_pi-1)*pi_y,pi_x+fr_side,pi_y+fr_side+(n_pi-1)*pi_y);
        if(n_pi>1) for(x=[0:n_pi-2]) {
            if(!dh_hide_tr) xline(m_x1,m_y2+x*pi_y,    -fr_side,pi_y+x*pi_y);
            if(!dh_hide_br) xline(m_x2,(dh_center_bot&&dh_hide_bl) ? pi_y/2 : m_y2+x*pi_y,pi_x+fr_side,pi_y+x*pi_y);
        }
    }
    if(top) {
        if (with_bat) {
            xline(m_x2+1,-fr_side+1,pi_x+fr_side,-fr_side);
        } else {
            if(!dh_hide_bl)
                xline(m_x2,(dh_center_bot&&dh_hide_br) ? pi_y/2 : m_y1,pi_x+fr_side,-fr_side);
            if(!dh_hide_tl) xline(m_x1,m_y1,    -fr_side,-fr_side);
            if(n_pi>1) for(x=[1:n_pi-1]) {
                if(!dh_hide_bl)xline(m_x2,(dh_center_bot && dh_hide_br ? pi_y/2 : m_y1)+x*pi_y,pi_x+fr_side,x*pi_y);
                if(!dh_hide_tl)xline(m_x1,m_y1+x*pi_y,    -fr_side,x*pi_y);
            }
        }

    } else {
        if(!dh_hide_bl)xline(m_x2,(dh_center_bot&&dh_hide_br) ? pi_y/2 : m_y1,pi_x+fr_side,    -fr_side);
        if(!dh_hide_tl) xline(m_x1,m_y1,    -fr_side,    -fr_side);
        if(n_pi>1) for(x=[1:n_pi-1]) {
            if(!dh_hide_bl) {
                xline(m_x2,(dh_center_bot && dh_hide_br ? pi_y/2 : m_y1) +x*pi_y,pi_x+fr_side, x*pi_y);
            }
            if(!dh_hide_tl) xline(m_x1,m_y1+x*pi_y,    -fr_side, x*pi_y);
        }
    }
    if(dh_center_bot && !dh_hide_bl && !dh_hide_br)
        for(x=[0:n_pi-1])
            line(m_x2,m_y1+x*pi_y,    m_x2,m_y2+x*pi_y);
    //xline(0,0,-fr_side,-fr_side);
    //xline(0,pi_y,-fr_side,pi_y+fr_side);
}

module bases() {
    // ("BASE_D",-fr_side,pi_x+fr_side);
    translate([-fr_side,-fr_side,0]) rotate(0) children();
    translate([-fr_side,pib_y+(n_pi-1)*pi_y,0]) rotate(-90) children();
    translate([pi_x+fr_side,-fr_side,0]) rotate(90) children();
    translate([pi_x+fr_side,pib_y+(n_pi-1)*pi_y,0]) rotate(180) children();
}

module bases_i() {
    // ("BASE_D",-fr_side,pi_x+fr_side);
    if(n_pi>1) for(x=[1:n_pi-1]) {
        translate([-fr_side,x*pi_y,0]) rotate(-90) children();
        translate([pi_x+fr_side,x*pi_y,0]) rotate(90) children();
    }
}

module clamp() {
    h_cl = pi_bottom+h_f+((with_clamp && cl_top) ? board_z2 : board_z);
    b_cl = pi_bottom+h_f;
    rotate([90,0,0]) rotate([0,90,0]) linear_extrude(cl_width, center=true) polygon([[0,0],[cl_depth,0],[cl_depth,b_cl],[0,b_cl],[0,h_cl],[cl_depth_top,h_cl+cl_height],[-cl_depth,h_cl+cl_height],[-fr_side,0]]);
    // cube([cl_width,edge_dm,pi_bottom+h_f+board_z+cl_height]);
}

module all_clamps() {
    off=cl_offset+cl_width/2;
    if(!cl_skip_x1b) translate([pi_x-off,0,0]) rotate(0) children();
    if(!cl_skip_x1a) translate([off,0,0]) rotate(0) children();
    if(!cl_skip_y1a) translate([0,off,0]) rotate(-90) children();
    if(!cl_skip_y1b) translate([0,pi_y-off,0]) rotate(-90) children();
    if(!cl_skip_y2b) translate([pi_x-off,pi_y,0]) rotate(180) children();
    if(!cl_skip_y2a) translate([off,pi_y,0]) rotate(180) children();
    if(!cl_skip_x2a) translate([pi_x,off,0]) rotate(90) children();
    if(!cl_skip_x2b) translate([pi_x,pi_y-off,0]) rotate(90) children();
}

module bottom() {
    frame();
    // bases() f_base();
    if(with_clamp && !cl_top) {
        all_clamps() clamp();
    } else {
        bottom_pins();
        bottom_mounts();
    }
    bottom_to_top();
    if($preview) {
        color([0.3,0.8,0.3,0.3])
        translate([0,0,bat_z_])
        cube([pi_x,pi_y,board_z]);
    }
}

module bottom_to_top() {
    s_in=edge_d/2;
    difference() {
        bases() {
            translate([s_in,s_in,h_f-_d]) cylinder(h=h_total-h_f+h_ppin,d=w_f, $fn=12);
            hull() {
                translate([s_in,s_in,h_f]) cylinder(h=_d,d=w_f, $fn=12);
                f_base();
            }
        }
        flip_top() bases() f_base_top();
    }

    difference() {
        bases_i() {
            translate([0,s_in,h_f-_d]) cylinder(h=h_total-h_f+h_ppin,d=w_f, $fn=12);
            translate([s_in,s_in,h_f]) cylinder(h=_d,d=w_f, $fn=12);
        }
        flip_top() bases_i() f_base_top_i();
    }
}

module top() {
    translate([pi_x,0,h_f]) rotate([0,180,0]) frame(true);
    if (edge_top) {
        bases() f_base_top();
        bases_i() f_base_top_i();
    } else
        bases() f_base();
    if (!with_clamp) top_pins(); else if(cl_top) all_clamps() clamp();
    if (with_bat) bat_pins();
}


module _pins(rev=false,skip2=false) {
    x1=rev?pi_x-m_x1:m_x1;
    x2=rev?pi_x-m_x2:m_x2;
    for(x=[0:n_pi-1]) {
        if(!dh_hide_tl) translate([x1,m_y1+x*pi_y,0]) children();
        if(dh_center_bot)
            translate([x2,pi_y/2+x*pi_y,0]) children();
        else {
            if(!dh_hide_bl) translate([x2,m_y1+x*pi_y,0]) children();
            }
        if(!skip2) {
            if(!dh_center_bot && !dh_hide_br)
                translate([x2,m_y2+x*pi_y,0]) children();
            if(!dh_hide_tr) translate([x1,m_y2+x*pi_y,0]) children();
        }
    }
}
module _bat_pins() {
    x1=pi_x-bat_x1;
    x2=pi_x-bat_x2;

    translate([x1,bat_y1,0]) children();
    translate([x2,bat_y1,0]) children();
    translate([x2,bat_y2,0]) children();
    translate([x1,bat_y2,0]) children();
}

module _pin(d,h,dt=-1,off=0){
    dd=(dt>0)?dt:d;
    translate([0,0,off+h/2]) cylinder(h=h,d1=d,d2=dd, center=true, $fn=12);
}

module bottom_mounts() {
    _pins()
    _pin(d=w_f,dt=d_hb,h=bat_z_-h_f/2, off=h_f/2);
}

module bottom_pins(skip2=false) {
    _pins()
    _pin(h=board_zp,d=d_h,dt=d_h-d_hx, off=bat_z_-_d);
}

module top_pins() {
    h_p = h_total-board_z-bat_z_;
    _pins(rev=true,skip2=with_bat)
    difference() {
        _pin(h=h_p-h_f/2,d=w_f,dt=d_hb, off=h_f/2);
        _pin(h=2*board_z,dt=d_h+d_d,d=d_h-d_hx+d_d, off=h_p-2*board_z+_d2);
    }
}

module bat_pins() {
    x1=pi_x-bat_x1;
    x2=pi_x-bat_x2;
    off=bat_x1+fr_side;

    h_b=bat_top;
    _bat_pins() {
        _pin(d=w_f,dt=d_hb,h=h_b-h_f/2, off=h_f/2);
        _pin(h=2*board_z,d=d_h,dt=d_h-d_hx, off=h_b-_d);
    }
    translate([x1-10, bat_y2+10+off, 0]) _pin(d=w_f,h=h_b-h_f/2,off=h_f/2);
    translate([x2+11+off-bat_off,bat_y2+10+off,0]) _pin(d=w_f,h=h_b-h_f/2,off=h_f/2);
}
