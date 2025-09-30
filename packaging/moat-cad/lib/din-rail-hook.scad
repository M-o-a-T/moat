rail_brim=35.1;

module din_rail_hook(depth, len=0, ridge=0, dw=0, cut=0, slot=false){
    // Din-Rail - Hutschiene 35m
    brim=rail_brim;
    rail_height=1.1;

    // DIN rail hook
    spring_l=15;
    spring_d=2.5;
    spring_slot=0.9;
    bar_width=2.5;
    hook=4;
    min_len=rail_brim-spring_slot;
    brim2=brim-spring_slot;

    _d=0.01;
    _d1=_d; _d2=2*_d; _d3=3*_d;
    mlen=(len>min_len)?len:min_len;
    aux=mlen-brim+spring_slot-dw;
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
    hsd=1.1; // hole slot depth
    hh=2; // height
    hw=depth/10; // hole's wall strength

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
            translate([_d2,0,0]) rotate([0,-90,0])
                linear_extrude(ridge/2+dw+_d2, convexity=20)
                    polygon([[0,0],[depth,0],[depth/2,depth/1.4]]);

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
