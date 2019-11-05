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

FakeClient fc_alloc(u_int8_t n_wires);
void fc_free(FakeClient fc);
char fc_connect(FakeClient fc, const char *sockname);
char fc_process(FakeClient fc);
int fc_timeout(FakeClient fc);
void fc_timer(FakeClient fc);
void fc_send(FakeClient fc, BusMessage msg, u_int8_t prio);

#endif
