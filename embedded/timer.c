#include "embedded/timer.h"
#include <memory.h>

static MTIMER timer_root NO_INIT;
static mtimer_delay_t last_timer NO_INIT;
static mtimer_delay_t d_res NO_INIT;
static MTICK tick_root NO_INIT;
static MTICK tick_next NO_INIT;

IN_C void mtick_init(MTICK mt, mtimer_proc proc)
{
    mt->proc = proc;
    mf_set(&mt->mf, 0);
    mt->next = tick_root;
    tick_root = mt;
}

static void run_ticks() {
    if (tick_next == NULL) {
        if (tick_root == NULL)
            return;
        tick_next = tick_root;
    }

    MTICK tick = tick_next;
    tick_next = tick->next;
    if (mf_tick(&tick->mf))
        (*tick->proc)();
}

IN_C void setup_timer()
{
    timer_root = NULL;
    last_timer = 0;
    d_res = 0;

    tick_root = NULL;
    tick_next = NULL;
}

IN_C void loop_timer(mtimer_delay_t timer)
{
    mtimer_delay_t d = timer-last_timer + d_res;
    if (tick_next || timer < last_timer)
        run_ticks();
    last_timer=timer;

    if(!timer_root) {
        d_res = 0;
        return;
    }
    if (timer_root->delay > d) {
        timer_root->delay -= d;
        d_res = 0;
        return;
    }
    MTIMER mt = timer_root;
    d -= mt->delay;
    timer_root = mt->next;
    if (timer_root)
        timer_root->prev = NULL;
    mt->delay = ~0;
    d_res = d;
    (*mt->proc)();
}

IN_C void mtimer_init(MTIMER mt, mtimer_proc proc)
{
    mt->delay = ~0;
    mt->proc = proc;
}

IN_C void mtimer_schedule(MTIMER mt, mtimer_delay_t delay)
{
    if (timer_root) {
        MTIMER pt = timer_root;
        while(pt->next && delay > pt->delay) {
            delay -= pt->delay;
            pt = pt->next;
        }
        if (delay <= pt->delay) { // insert before this
            pt->delay -= delay;
            if(pt->prev)
                pt->prev->next = mt;
            else
                timer_root = mt;
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
        timer_root = mt;
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
        timer_root = mt->next;
    }
    mt->delay = ~0;
}

