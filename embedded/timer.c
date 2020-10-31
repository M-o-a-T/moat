#include "embedded/timer.h"
#include <memory.h>

static MTIMER root;
mt_delay_t last_ts, d_res;
static MTICK mt_root;
static MTICK mt_next;

IN_C void mtick_init(MTICK mt, mtimer_proc proc)
{
    mt->proc = proc;
    mf_set(&mt->mf, 0);
    mt->next = mt_root;
    mt_root = mt;
}

IN_C static void run_ticks();
static void run_ticks() {
    if (mt_next == NULL) {
        if (mt_root == NULL)
            return;
        mt_next = mt_root;
    }

    MTICK mt = mt_next;
    mt_next = mt->next;
    if (mf_tick(&mt->mf))
        (*mt->proc)();
}

IN_C void setup_timer()
{
    root = NULL;
    last_ts = 0;
    d_res = 0;

    mt_root = NULL;
    mt_next = NULL;
}

IN_C void loop_timer(mt_delay_t ts)
{
    mt_delay_t d = ts-last_ts + d_res;
    if (mt_next || ts < last_ts)
        run_ticks();
    last_ts=ts;

    if(!root) {
        d_res = 0;
        return;
    }
    if (root->delay > d) {
        root->delay -= d;
        d_res = 0;
        return;
    }
    MTIMER mt = root;
    d -= mt->delay;
    root = mt->next;
    if (root)
        root->prev = NULL;
    mt->delay = ~0;
    d_res = d;
    (*mt->proc)();
}

IN_C void mtimer_init(MTIMER mt, mtimer_proc proc)
{
    mt->delay = ~0;
    mt->proc = proc;
}

IN_C void mtimer_schedule(MTIMER mt, mt_delay_t delay)
{
    if (root) {
        MTIMER pt = root;
        while(pt->next && delay > pt->delay) {
            delay -= pt->delay;
            pt = pt->next;
        }
        if (delay <= pt->delay) { // insert before this
            pt->delay -= delay;
            if(pt->prev)
                pt->prev->next = mt;
            else
                root = mt;
            mt->prev = pt->prev;

            pt->prev = mt;
            mt->next = pt;
        } else { // insert at end
            delay -= pt->delay;
            mt->prev = pt;
            pt->next = mt;
            mt->next = NULL;
        }
    } else {
        mt->next = NULL;
        mt->prev = NULL;
        root = mt;
    }
    mt->delay = delay;
}

IN_C void mtimer_cancel(MTIMER mt)
{
    if(mt->delay == ~0)
        return;
    if (mt->next) {
        mt->next->delay += mt->delay;
        mt->next->prev = mt->prev;
    }
    if (mt->prev) {
        mt->prev->next = mt->next;
    } else {
        root = mt->next;
    }
    mt->delay = ~0;
}

