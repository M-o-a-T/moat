#include "moatbus/util.h"

// for cpu_random
#include "embedded/main.h"

#include "embedded/logger.h"

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

u_int16_t mf_as16(u_int8_t mm)
{
    if(mm < 32)
        return mm;
    if (mm >= 208) // 65536
        return 0xFFFF;
    u_int8_t exp = (mm>>4) -1;
    mm = 0x10 | (mm&0xf);
    u_int16_t v = (1<<exp) * mm;
    return v;
}

void mf_set_randfract(minifloat *m, u_int8_t mm, u_int8_t lower)
{
    u_int16_t f = mf_as16(mm);
    mf_set(m, mf_random((f>>3)*lower, f));
}

void mf_set(minifloat *m, u_int8_t f)
{
    m->m = f;
    mf_reset(m);
}

void mf_set_shift(minifloat *m, u_int8_t f, u_int8_t shift)
{
    u_int32_t v;
    if(f <= 32)
        v = f;
    else {
        u_int8_t exp = (f>>4) -1;
        f = 0x10 | (f&0xf);
        v = (1<<exp) * f;
    }
    v = (v*shift) >> 3;
    m->vl = v&0xFF;
    m->vh = v>>8;
    m->m = mf_get(m);
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
        return FALSE;
    ASSERT(m->vl || m->vh);
    if (m->vl) {
        m->vl -= 1;
        if (!m->vl && !m->vh) {
            mf_reset(m);
            return TRUE;
        }
        return FALSE;
    } else {
        m->vh -= 1;
        m->vl = ~0;
        return FALSE;
    }
}

u_int8_t mf_random(u_int16_t lo, u_int16_t hi)
{
    minifloat x;
    if(lo == 0)
        lo = 1;

    u_int16_t v = lo+cpu_random(hi-lo);
    x.vl = v&0xFF;
    x.vh = v>>8;
    return mf_get(&x);
}

