#ifndef MOATBUS_UTIL
#define MOATBUS_UTIL

#include "moatbus/common.h"

// TODO debugging
#define ASSERT(x) do {} while(0)

#include <sys/types.h>
#include "moatbus/type.h"

// fast small-integer powers
IN_C u_int16_t powi(u_int8_t x, u_int8_t y);

// ticks per second for timer-based minifloats
#define MINI_F 4

// minifloat timers
typedef struct _minifloat {
    u_int8_t m; // the actual float
    u_int8_t vl; // counter, low byte
    u_int16_t vh; // counter, high bytes
} minifloat;

// get the current value
IN_C u_int8_t mf_get(minifloat *m);

// set the current value. Note that a value of zero never triggers.
IN_C void mf_set(minifloat *m, u_int8_t f);

// reset the current value to the stored value
IN_C void mf_reset(minifloat *m);

// decrement the current value; if zero, reset and return True, else return False
IN_C bool mf_tick(minifloat *m);

// test if this minifloat ever triggers
static inline bool mf_is_zero(minifloat *m) { return m->m == 0; }
#endif

