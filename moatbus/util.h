#ifndef MOATBUS_UTIL
#define MOATBUS_UTIL

// TODO debugging
#define ASSERT(x) do {} while(0)

// ticks per second for timer-based minifloats
#define MINI_F 4

#include <sys/types.h>
#include "moatbus/type.h"

// fast small-integer powers
u_int16_t powi(u_int8_t x, u_int8_t y);

// minifloat timers
typedef struct _minifloat {
    u_int8_t m; // the actual float
    u_int8_t vl; // low byte
    u_int16_t vh; // high bytes
} minifloat;

// get the current value
u_int8_t mf_get(minifloat *m);

// set the current value
void mf_set(minifloat *m, u_int8_t f);

// reset the current value to the stored value
void mf_reset(minifloat *m);

// decrement the current value; if zero, reset and return True, else return False
bool mf_tick(minifloat *m);

// test if this minifloat ever triggers
static inline bool mf_is_zero(minifloat *m) { return m->m == 0; }
#endif

