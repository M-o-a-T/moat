#ifndef EMB_CLIENT_H
#define EMB_CLIENT_H

#include "moatbus/common.h"
#include "moatbus/message.h"

extern u_int8_t my_addr;

IN_C void setup_addr();
IN_C void setup_get_addr();

// True if the message is for me
IN_C char process_msg_in(BusMessage msg);

#endif
