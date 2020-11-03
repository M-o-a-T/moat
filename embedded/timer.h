#ifndef EMB_TIMER_H
#define EMB_TIMER_H

#include <stdarg.h>
#include "moatbus/common.h"
#include "moatbus/util.h"

/****
 * Timers. They have a resolution of MTIMER_RES, which overflows a 16-bit
 * value after ~1/4th second, which is nice because that happens to be the
 * min rsolution of a tick, see below.
 *
 * Timers are chained dynamically. Removing them is reasonably fast.
 *****/

// ticks per second. 2 means that a 16bit value overflows after ~1/4th
// second, which is nice for our mtick handler.
#define MTIMER_RES (1000000ULL >> 2)
#define MTIMER_READ() (micros()>>2)
typedef u_int16_t mtimer_delay_t;

// Convert microseconds to actual timer ticks.
// The -1/+1 is used so that any input >0 stays >0 no matter what.
// Try to only use this with const values.
#define MTIMER_USEC(us) ((us-1)*MTIMER_RES/1000000+1)

typedef void (mtimer_proc)();

typedef struct mtimer {
    struct mtimer *next;
    struct mtimer *prev;
    mtimer_delay_t delay;
    mtimer_proc *proc;
} *MTIMER;

IN_C void setup_timer();
IN_C void loop_timer(mtimer_delay_t ts);

IN_C void mtimer_init(MTIMER mt, mtimer_proc *proc);
IN_C void mtimer_schedule(MTIMER mt, mtimer_delay_t delay);
IN_C void mtimer_cancel(MTIMER mt);


/****
 * Tickers. They have a resolution of 1/MINI_F, i.e. 1/4th second,
 * and a max value of more than a day.
 *
 * Tickers are linked statically.
 * Use standard mf_* routines to manipulate their minifloat.
 *****/

typedef void (mf_proc)();

typedef struct mtick {
    minifloat mf;
    mf_proc *proc;
    struct mtick *next;
} *MTICK;

IN_C void mtick_init(MTICK mt, mtimer_proc proc);    

#endif
