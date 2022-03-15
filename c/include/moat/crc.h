/*
 * 16-bit CRC for the serial line.
 *
 * 11-bit CRC tables for the wire are generated dynamically,
 * thus not part of this code.
 */
#include <sys/types.h>
#include "moatbus/common.h"

IN_C u_int16_t mcrc16_update(u_int16_t crc, u_int8_t data);
IN_C u_int32_t mcrc32_update(u_int32_t crc, u_int8_t data);

