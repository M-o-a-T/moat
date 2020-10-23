#ifndef FAKEBUS_CLIENT
#define FAKEBUS_CLIENT

#include "moatbus/message.h"
#include "moatbus/handler.h"

typedef struct _FakeClient {
    int socket_fd;
    u_int16_t timeout;
    unsigned int timeout1;
    unsigned int timeout2;
    int8_t dest;

    BusHandler bus;

    // mainloop needs to clear in_msg and out_msg ASAP
    BusMessage in_msg; // incoming
    BusMessage out_msg; // outgoing, after processing
    enum HDL_RES out_result; // result of sending out_msg
    u_int8_t wire_in;
    char verbose;
} *FakeClient;

// allocate a client with `n_wires` wires
FakeClient fc_alloc(u_int8_t n_wires);

// free a client and its resources
void fc_free(FakeClient fc);

// connect the client to a fake bus at this socket
char fc_connect(FakeClient fc, const char *sockname);

// process a byte from the socket
char fc_process(FakeClient fc);

// return the next timeout (ms)
int fc_timeout(FakeClient fc);

// process a timeout from the socket
void fc_timer(FakeClient fc);

// queue a message for sending
void fc_send(FakeClient fc, BusMessage msg, u_int8_t prio);

#endif
