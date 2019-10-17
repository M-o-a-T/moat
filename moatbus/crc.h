#include <stdlib.h>

u_int8_t crc8_init();
u_int8_t crc8_update(u_int8_t crc, u_int8_t byte);
u_int8_t crc8_update_v(u_int8_t crc, u_int16_t byte, u_int8_t n_bits);
u_int8_t crc8_finish(u_int8_t crc);
u_int8_t crc8(u_int8_t *data, u_int16_t len);

u_int16_t crc16_init();
u_int16_t crc16_update(u_int16_t crc, u_int8_t byte);
u_int16_t crc16_update_v(u_int16_t crc, u_int16_t byte, u_int8_t n_bits);
u_int16_t crc16_finish(u_int16_t crc);
u_int16_t crc16(u_int8_t *data, u_int16_t len);
