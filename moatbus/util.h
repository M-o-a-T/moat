#ifndef MOATBUS_UTIL
#define MOATBUS_UTIL

// fast small-integer powers
static inline u_int16_t powi(u_int8_t x, u_int8_t y)
{
    u_int16_t res = 1;
    u_int16_t xx = x;

    while(1) {
        if (y&1)
            res *= xx;
        y >>= 1;
        if (!y)
            return res;
        xx *= xx;
    }
}

#endif

