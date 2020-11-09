#include "embedded/timer.h"
#include "embedded/main.h"
#include "embedded/logger.h"
#include <memory.h>

#include "Arduino.h"

static MTIMER timer_root NO_INIT;
static struct mtimer tick_timer NO_INIT;
static mtimer_delay_t last_timer NO_INIT;
static mtimer_delay_t d_res NO_INIT;
static MTICK tick_root NO_INIT;
static MTICK* tick_next NO_INIT;
static uint16_t tick_missed NO_INIT;

IN_C void mtick_init(MTICK mt, mtick_proc proc)
{
    mt->proc = proc;
    mf_set(&mt->mf, 0);
    mt->next = tick_root;
    tick_root = mt;
}

void start_tick(MTIMER _)
{
    // if not, we have a problem. Oh well.
    if (tick_next == NULL)
        tick_next = &tick_root;
    else
        tick_missed++;

    // time each tick should be at: qsec=250000/4==62500
    // usec/4 overflows: uov=65536; uov-qsec==3036
    mtimer_schedule(&tick_timer, 62500-1500+cpu_random(3001));
    // plus one to center around the median value. This will still drift,
    // so it doesn't really matter, but still :-)
}

IN_C void setup_timer()
{
    timer_root = NULL;
    last_timer = 0;
    d_res = 0;

    tick_missed = 0;
    tick_root = NULL;
    tick_next = NULL;
    mtimer_init(&tick_timer, start_tick);
    mtimer_schedule(&tick_timer, 31250+cpu_random(31250));
    // sometime during the late half of the next quarter second
}

static void run_ticks()
{
    MTICK tick = *tick_next;
    if (tick == NULL) {
        tick_next = NULL;
        return;
    }

    if (mf_tick(&tick->mf)) {
        // The callback may remove+free itself.
        // Thus we need to (temporarily?) unlink it.
        *tick_next = tick->next;
        if((*tick->proc)(tick)) {
            *tick_next = tick;
        } else {
            // *tick_next already points to the next entry at this time,
            // thus we don't need to do a thing
            return;
        }
    }
    // get the next entry, next go around
    tick_next = &tick->next;
}

IN_C void loop_timer()
{
    mtimer_delay_t timer = MTIMER_READ();
    mtimer_delay_t d = timer-last_timer + d_res;
    last_timer=timer;

    if (tick_next)
        run_ticks();

    if(!timer_root) {
        d_res = 0;
        return;
    }
    if (timer_root->delay > d) {
        // next timeout is simewhere in the future
        timer_root->delay -= d;
        d_res = 0;
        return;
    }
    MTIMER mt = timer_root;
    d -= mt->delay;
    mt->delay = 0;
    timer_root = mt->next;
    if (timer_root)
        timer_root->prev = NULL;
    d_res = d;
    (*mt->proc)(mt);
}

IN_C void mtimer_init(MTIMER mt, mtimer_proc proc)
{
    mt->delay = 0;
    mt->proc = proc;
}

IN_C void mtimer_schedule(MTIMER mt, mtimer_delay_t delay)
{
    delay = std::max(delay,(mtimer_delay_t)1);
    if (timer_root) {
        MTIMER pt = timer_root;
        // if delays are identical, go to the end. Keep the delay at
        // least 1. This ensures that delay==0 means "not enqueued".
        while(pt->next && delay >= pt->delay) {
            delay = std::max(delay - pt->delay, 1);
            pt = pt->next;
        }
        if (delay < pt->delay) { // insert before this
            if(pt->prev)
                pt->prev->next = mt;
            else
                timer_root = mt;
            mt->prev = pt->prev;

            pt->prev = mt;
            mt->next = pt;
        } else { // insert at end
            ASSERT(pt->next == NULL);
            delay = std::max(delay - pt->delay, 1);
            mt->prev = pt;
            pt->next = mt;
            mt->next = NULL;
        }
    } else {
        mt->next = NULL;
        mt->prev = NULL;
        mt->delay = delay;
        timer_root = mt;
    }
}

IN_C void mtimer_cancel(MTIMER mt)
{
    if(mt->delay == 0)
        return;
    if (mt->next) {
        mt->next->delay += mt->delay;
        mt->next->prev = mt->prev;
    }
    if (mt->prev) {
        mt->prev->next = mt->next;
    } else if(timer_root == mt) {
        timer_root = mt->next;
    } else {
        logger("BadCancel timer x%x",mt);
    }
    mt->delay = 0;
}

