/*
 * 16-bit CRC for the serial line.
 *
 * 11-bit CRC tables for the wire are generated dynamically,
 * thus not part of this code.
 */
#include <sys/types.h>

u_int16_t crc16_update(u_int16_t crc, u_int8_t data);

