#ifndef EMB_TIMER_H
#define EMB_TIMER_H

#include <stdarg.h>
#include "moatbus/common.h"
#include "moatbus/util.h"

// The usual: setup and loop
IN_C void setup_timer();
IN_C void loop_timer();


/****
 * Timers. They have a resolution of MTIMER_RES, which overflows a 16-bit
 * value after ~1/4th second, which works because that happens to be the
 * min resolution of a tick, see below.
 *
 * Timers are chained dynamically. Removing them is reasonably fast.
 *****/

// Resolution.
#define MTIMER_RES (1000000ULL >> 2)
#define MTIMER_READ() (micros()>>2)
typedef u_int16_t mtimer_delay_t;

// Convert microseconds to actual timer ticks.
// The -1/+1 is used so that any input >0 stays >0 no matter what.
// Try to only use this with const values so that the compiler can optimize it.
#define MTIMER_USEC(us) ((us-1)*MTIMER_RES/1000000+1)

typedef struct mtimer *MTIMER;

// Callback type.
typedef void (mtimer_proc)(MTIMER);

struct mtimer {
    struct mtimer *next;
    struct mtimer *prev;
    mtimer_delay_t delay;
    mtimer_proc *proc;
};

IN_C void mtimer_init(MTIMER mt, mtimer_proc *proc);
IN_C void mtimer_schedule(MTIMER mt, mtimer_delay_t delay);
IN_C void mtimer_cancel(MTIMER mt);


/****
 * Tickers. They have a resolution of 1/MINI_F, i.e. 1/4th second,
 * and a max value of more than a day.
 *
 * Tickers are linked statically.
 * Use standard mf_* routines to manipulate their minifloat.
 *
 * If your procedure returns False, the entry will be unlinked.
 * Otherwise the timer will be restarted.
 *****/

typedef struct mtick *MTICK;

// If the callback returns FALSE, the ticker will be unlinked.
// (It's OK to free the data structure in the callback.)
typedef bool (mtick_proc)(MTICK);

struct mtick {
    MTICK next;
    minifloat mf;
    mtick_proc *proc;
};

// Setup data and add to chain. The minifloat is untouched.
IN_C void mtick_init(MTICK mt, mtick_proc proc);    

#endif
