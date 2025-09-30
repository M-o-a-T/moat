//STACKABLE RESISTOR STORAGE BOX [Customizable]
//Created by Bram Vaessen 2018


// preview[view:south, tilt:top diagonal]

/* [Enclosing dimensions] */
//the width X (mm) of the drawer
drawWidth = 53;
//the depth Y (mm) of the drawer
drawDepth = 143;
//the height Z (mm) of the drawer space
totalHeight = 36.5;

/* [Compartments] */

//The number of compartments in the drawer next to each other
compartXCount = 2;
//The number of compartments in the drawer behind each other
compartYCount = 5;
//This drawer's height, in compartZmultiple units. Eg if compartZmultiple=4 you can stack two 1-height and one 2-height drawers into it
compartZCount = 2; //[1:1:5]
//How many units to divide the vertical space into
compartZmultiple = 4; //[1:1:6]

// smoothing for drawers
smoothRadius=2.5;

// calculate height of single drawer
drawHeight = (totalHeight-smoothRadius)*compartZCount/compartZmultiple+smoothRadius;

// tilt-out-prevention tongue height
tongueHeight = 4.5; // set to zero to skip
// tilt-out-prevention tongue width
tongueWidth = 28;

/* [Tolerances] */
//the amount of extra space (mm) on the side of the drawers, on each side (reprint box after changing, unless using 'custom sized box', then reprint drawer)
drawHorSpace = 0.25;
//the amount of extra space (mm) on top and bottom of drawers, on each side (reprint box after changing, unless using 'custom sized box', then reprint drawer)
drawVertSpace = 0.35;
//the amount of extra space (mm) on the behind the drawer (reprint box after changing, unless using 'custom sized box', then reprint drawer)
drawBackSpace = 0.2;


/* [Your Printer Settings] */
//the layer width that you print with
layerWidth=0.45;
//the layer height that you print with
layerHeight=0.3;
//first layer height
firstLayerHeight=0.35;
//first layer width
firstLayerWidth=0.6;

///////////////////////////////////////////////////


/* [Hidden] */
smoothQuality=$preview?12:20;

drawDividerWidth = 2*layerWidth;
drawOutsideWidth = 3*layerWidth;
drawBottomHeight = firstLayerHeight+layerHeight;

drawFrontExtraDepth=1*layerWidth;
drawBackExtraDepth=3*layerWidth; // required for tongue's groove

drawFrontExtra = max(0, smoothRadius - drawOutsideWidth);

compartWidth = (drawWidth - drawOutsideWidth*2 - drawDividerWidth*(compartXCount-1)) / compartXCount;
compartDepth = (drawDepth - drawOutsideWidth*2 -drawFrontExtraDepth-drawBackExtraDepth -drawDividerWidth*(compartYCount-1))/compartYCount;
compartHeight = drawHeight-drawBottomHeight;

handleWidth = drawWidth/8;
handleWidthOld = drawWidth/12;
handleHeight = drawHeight + 2*layerHeight - smoothRadius;

handleDepth = handleHeight*0.5;
handleThickness = layerWidth*4;

_d1=0.001;
_d2=2*_d1;

Drawer();

module Drawer()
{
    y = -drawDepth/2;
    z = drawHeight/2;

    startX = -drawWidth/2 + drawOutsideWidth + compartWidth/2;
    startY = -drawDepth/2 + drawOutsideWidth + compartDepth/2 + drawFrontExtraDepth;
    stepX = compartWidth + drawDividerWidth;
    stepY = compartDepth + drawDividerWidth;
    indentWidth = drawWidth - drawOutsideWidth*2;
    indentDepth = drawDepth - drawOutsideWidth*2;

    difference()
    {
        DrawerBase();
        //cut out compartments
        for (x=[0:compartXCount-1]) for (y=[0:compartYCount-1])
            translate([startX + x*stepX, startY + y*stepY, drawBottomHeight])
                SmoothCube([compartWidth, compartDepth, compartHeight+2]);
        //cut out top
        translate([0,0,drawHeight-smoothRadius])
            DrawerBase(spaced=1);
    }

    translate([0,y,0]) HandleThin();
}

module DrawerTongue()
{
    if(tongueHeight)
    translate([0,drawDepth/2,0])
    hull() {
        translate([tongueWidth/2-smoothRadius,0,tongueHeight-smoothRadius]) rotate([90,0,0]) cylinder(h=drawOutsideWidth,d=smoothRadius*2);
        translate([-tongueWidth/2+smoothRadius,0,tongueHeight-smoothRadius]) rotate([90,0,0]) cylinder(h=drawOutsideWidth,d=smoothRadius*2);
        translate([-tongueWidth/2,-drawOutsideWidth,-tongueHeight-smoothRadius]) cube([tongueWidth,drawOutsideWidth,_d1]);
    }
}

module DrawerSpace()
{
    if(tongueHeight)
        translate([-drawHorSpace,drawDepth/2-drawHorSpace-_d1,0])
        hull() {
            translate([-tongueWidth/2,-drawOutsideWidth,tongueHeight+drawOutsideWidth*sqrt(2)])
                rotate([45,0,0])
                cube([tongueWidth+drawHorSpace*2,(drawOutsideWidth+drawHorSpace+_d2)*sqrt(2),_d1]);
            translate([-tongueWidth/2,-drawOutsideWidth-_d1,-tongueHeight-smoothRadius])
                cube([tongueWidth+drawHorSpace*2,drawOutsideWidth+drawHorSpace+_d2,_d1]);
        }
}

module DrawerBase(spaced=0)
{
    difference() {
        union() {
            SmoothCubeS(layerWidth,drawWidth, drawDepth, drawHeight);
            translate([0,0,drawHeight]) DrawerTongue();
        }
        DrawerSpace();
    }
}


module HandleThin()
{
    startDiam = 1.5*handleWidth;
    endDiam = handleWidth;
    endDiamOld = 0.85 * handleWidthOld;
    middleDiam = endDiamOld+2*layerWidth;
    length = 2 * handleWidth;
    lengthOld = 2 * handleWidthOld;
    height = drawHeight-layerHeight-smoothRadius;
    cubeSize=drawWidth;
    knobPlus=endDiam/5;
    ringPasses=8;
    slope=30;

    difference() {
        union() {
            translate([0,layerWidth,0]) difference() {
                translate([-(startDiam+middleDiam)/2,-startDiam/2,0]) cube([startDiam+middleDiam,startDiam/2,height]);
                translate([-(startDiam+middleDiam)/2,-startDiam/2,-_d1]) cylinder(d=startDiam, h=height+_d2, $fn=32);
                translate([(startDiam+middleDiam)/2,-startDiam/2,-_d1]) cylinder(d=startDiam, h=height+_d2, $fn=32);
                translate([0,handleWidth+_d1+layerWidth,0])
                    cube([handleWidth*2, handleWidth*2, height*2.1], center=true);
            }
            translate([0,-length,0]) cylinder(d=endDiam, h=height, $fn=32);
            translate([0,-length/2,0]) CenterCube([middleDiam, length,height]);
            translate([0,-length,height+knobPlus]) sphere(d=endDiam-layerWidth*5-layerHeight, $fn=32);
            translate([0,-length,height]) cylinder(d=endDiam-layerWidth*5-layerHeight, h=knobPlus,$fn=32);
            difference() {
                translate([0,-length,0]) cylinder(d=endDiam+layerWidth*(ringPasses+3), h=layerHeight, $fn=32);
                translate([0,-length,-_d1]) cylinder(d=endDiam+layerWidth*3, h=layerHeight+_d2, $fn=32);
                translate([-(endDiam+layerWidth*(ringPasses+4))/2,-length+firstLayerWidth/2,-_d1]) cube([endDiam+layerWidth*(ringPasses+4),(endDiam+layerWidth*(ringPasses+3))/2+.01,layerHeight+_d2]);
            }
            for(x=[0,1,2,3,4])
            translate([0,-length,0]) rotate(45*x) translate([-endDiam+5*layerWidth,-firstLayerWidth/2,0]) cube([4*layerWidth,firstLayerWidth,layerHeight]);
        }
        if(0)translate([0,endDiam/2-cubeSize/sqrt(2)-length,-_d1])
        rotate([45,0,0])
            cube([cubeSize,cubeSize,cubeSize], center=true);
        if(0)translate([0,layerWidth,cubeSize*(1+1/sqrt(2))-endDiam/sqrt(2)-layerWidth])
        rotate([-45,0,0])
            cube([cubeSize,cubeSize,cubeSize], center=true);
        translate([-cubeSize/2,-smoothRadius*tan(slope)-layerWidth,-0.01])
        rotate([-slope,0,0])
            cube([cubeSize,cubeSize,cubeSize]);
        translate([0,-length,-_d1]) cylinder(d=endDiam-layerWidth*4, h=knobPlus+_d2,$fn=32);
        translate([0,-length,knobPlus]) sphere(d=endDiam-layerWidth*5, $fn=32);
        if(0) translate([0,-lengthOld,0]) sphere(d=endDiamOld-layerWidth*2, $fn=32);
    }


}

module CenterCube(size)
{
    translate([0,0,size[2]/2])
        cube(size=size,center=true);
}

module SmoothCube(size)
{
    sr2 = smoothRadius*2;
    hull()
    {

        translate([0,0,size[2]/2])
        {
            cube([size[0], size[1]-sr2, size[2]-sr2], center=true);
            cube([size[0]-sr2, size[1], size[2]-sr2], center=true);
            cube([size[0]-sr2, size[1]-sr2, size[2]], center=true);
        }

        for (x=[-1,1]) for (y=[-1,1])
        {
            translate([x*(size[0]/2-smoothRadius), y*(size[1]/2-smoothRadius), smoothRadius])
                sphere(r=smoothRadius, $fn=smoothQuality);
        }
        for (x=[-1,1]) for (y=[-1,1])
        {
            translate([x*(size[0]/2-smoothRadius), y*(size[1]/2-smoothRadius), size[2]])
                cylinder(r=smoothRadius, h=_d1, $fn=smoothQuality);
        }

    }
}

module SmoothCubeS(hs,sx,sy,sz)
{
    sr2 = smoothRadius*2;
    translate([0,0,-hs])
    hull()
    {
        for (x=[-1,1]) for (y=[-1,1])
        {
            translate([x*(sx/2-smoothRadius), y*(sy/2-smoothRadius), smoothRadius])
                sphere(r=smoothRadius-hs, $fn=smoothQuality);
        }
        for (x=[-1,1]) for (y=[-1,1])
        {
            translate([x*(sx/2-smoothRadius), y*(sy/2-smoothRadius), sz])
                cylinder(r=smoothRadius, h=_d1, $fn=smoothQuality);
        }

    }
}
