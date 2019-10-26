#ifndef MOATBUS_UTIL
#define MOATBUS_UTIL

static inline u_int16_t powi(u_int8_t x, u_int8_t y)
{
    u_int16_t res = 1;
    while (y-- > 0)
        res *= x;
    return res;
}

#endif

