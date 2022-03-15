// check minifloats

#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include "moatbus/util.h"

void die(const char *s) {
    fprintf(stderr,"Fail: %s\n", s);
    exit(1);
}

void main() {
    minifloat mf;
    mf_set(&mf,3);
    if(mf_get(&mf) != 3) die("A");
    if(mf_tick(&mf)) die("b");
    if(mf_tick(&mf)) die("c");
    if(!mf_tick(&mf)) die("e");
    if(mf_tick(&mf)) die("f");
    if(mf_tick(&mf)) die("g");
    if(!mf_tick(&mf)) die("h");
    if(mf_tick(&mf)) die("f");
    if(mf_get(&mf) != 2) die("h");
    if(mf_is_stopped(&mf)) die("i");
    mf_reset(&mf);
    if(mf_get(&mf) != 3) die("j");
    mf_set(&mf,0xF0);
    printf("MF %04x%02x\n", mf.vh,mf.vl);
    exit(0);

}
