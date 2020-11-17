#ifndef MOATBUS_UTIL
#define MOATBUS_UTIL

#include <sys/types.h>

#include "moatbus/common.h"

// TODO debugging
#define ASSERT(x) do {} while(0)

#define container_of(ptr, type, member) ({\
    char *__mptr = (char *)(ptr); \
    ((type *)(__mptr - offsetof(type, member))); })

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

// expand the minifloat to an at-most-16bit value
IN_C u_int16_t mf_as16(u_int8_t mm)  ;

// Set to a MF representing a random pos between mm*lower/8 and mm
IN_C void mf_set_randfract(minifloat *m, u_int8_t mm, u_int8_t lower);

// set the current value. Note that a value of zero never triggers.
IN_C void mf_set(minifloat *m, u_int8_t f);

// set the current value, divided by 8 and multiplied by "shift".
// The actual float is set as an approximation of the result.
IN_C void mf_set_shift(minifloat *m, u_int8_t f, u_int8_t shift);

// reset the current value to the stored value
IN_C void mf_reset(minifloat *m);

// decrement the current value; if zero, reset and return True, else return False
IN_C bool mf_tick(minifloat *m);

// decrement the current value; if zero, reset and return True, else return False
static inline void mf_stop(minifloat *m) { m->m = 0; }

// test if this minifloat ever triggers
static inline bool mf_is_stopped(minifloat *m) { return m->m == 0; }

// random value, equally distributed
IN_C u_int8_t mf_random(u_int16_t lo, u_int16_t hi);

#endif

