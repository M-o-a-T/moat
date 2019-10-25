/*
 * These calls update a 6- or 11-bit CRC with an n-bit wire state.
 *
 * n must be <=6, no higher bits of the value may be set.
 *
 * There is no bit reversal or anything going on here, so you can't
 * (easily) add the CRC result to the data and expect to arrive at a zero  
 * (or -1) CRC. That's intentional because the MoaT bus doesn't work that   
 * way anyway.
 */
#include <sys/types.h>

u_int8_t crc6_update(u_int8_t crc, u_int8_t data, u_int8_t n);
u_int16_t crc11_update(u_int16_t crc, u_int8_t data, u_int8_t n);

u_int8_t crc8_update(u_int8_t crc, u_int8_t data, u_int8_t n);
u_int16_t crc16_update(u_int16_t crc, u_int8_t data, u_int8_t n);

