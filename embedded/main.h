#ifndef EMB_MAIN_H
#define EMB_MAIN_H

#include <stdarg.h>

#include "moatbus/message.h"

void send_serial_msg(BusMessage msg, uint8_t prio);
void send_bus_msg(BusMessage msg, uint8_t prio);

void process_serial_msg(BusMessage msg, uint8_t prio);
char process_bus_msg(BusMessage msg);

void setup_polled();
void loop_polled();

void setup_serial();
void loop_serial();
bool serial_is_idle();


unsigned int memspace();


#define cpu_serial_len (3*4)
void cpu_serial(u_int8_t *buffer);
u_int16_t cpu_random(u_int16_t max);

#endif
