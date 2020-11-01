#ifndef EMB_MAIN_H
#define EMB_MAIN_H

#include <stdarg.h>

#include "moatbus/message.h"

// Send message to serial or bus, depending on address
void send_msg(BusMessage msg);

#ifdef MOAT_REPEATER
void process_serial_msg(BusMessage msg, uint8_t prio);
#endif
char process_bus_msg(BusMessage msg);

// external
void setup_polled();
void loop_polled();

// external
void setup_serial();
void loop_serial();

// called from address assigner to note that we're OK
void setup_addr_done();

// free heap memory
unsigned int memspace();


#define cpu_serial_len (3*4)
u_int8_t *cpu_serial();
u_int16_t cpu_random(u_int16_t max);

#endif
