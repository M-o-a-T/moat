#include "moatbus/util.h"

// for cpu_random
#include "embedded/main.h"

// fast small-integer powers
u_int16_t powi(u_int8_t x, u_int8_t y)
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

u_int8_t mf_get(minifloat *m)
{
    if(m->vh == 0 && m->vl <= 32)
        return m->vl;

    u_int32_t f = (m->vh << 8) | m->vl;
    u_int16_t exp = 1;
    while (f >= 32) { // normalization: the upper bit is implied
        f >>= 1;
        exp += 1;
    }
    return (exp<<4) | (f&0xf);
}

void mf_set(minifloat *m, u_int8_t f)
{
    m->m = f;
    mf_reset(m);
}

void mf_reset(minifloat *m)
{
    if (m->m <= 32) {
        m->vh = 0;
        m->vl = m->m;
        return;
    }
    u_int8_t mm = m->m;
    u_int8_t exp = (mm>>4) -1;
    mm = 0x10 | (mm&0xf);
    u_int32_t v = (1<<exp) * mm;
    m->vl = v&0xFF;
    m->vh = v>>8;
}

bool mf_tick(minifloat *m)
{
    if (!m->m)
        return false;
    ASSERT(m->vl || m->vh);
    if (m->vl) {
        m->vl -= 1;
        if (!m->vl && !m->vh) {
            mf_reset(m);
            return true;
        }
        return false;
    } else {
        m->vh -= 1;
        m->vl = ~0;
        return false;
    }
}

u_int8_t mf_random(u_int16_t lo, u_int16_t hi)
{
    minifloat x;
    u_int16_t v = lo+cpu_random(hi-lo);
    x.vl = v&0xFF;
    x.vh = v>>8;
    return mf_get(&x);
}

