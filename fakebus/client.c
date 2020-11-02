#include <stdlib.h>
#include <stdarg.h>
#include <stdio.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <unistd.h>
#include <string.h>

#include "moatbus/message.h"
#include "moatbus/handler.h"
#include "fakebus/client.h"

static void fcb_set_timeout(void *ref, u_int16_t delay);
static void fcb_set_wire(void *ref, u_int8_t bits);
static u_int8_t fcb_get_wire(void *ref);
static char fcb_process(void *ref, BusMessage msg);
static void fcb_transmitted(void *ref, BusMessage msg, enum HDL_RES result);
static void fcb_debug(void *ref, const char *text, va_list arg);
static void fcb_report_error(void *ref, enum HDL_ERR err);

struct BusCallbacks bcb = {
    .set_timeout = fcb_set_timeout,
    .set_wire = fcb_set_wire,
    .get_wire = fcb_get_wire,
    .process = fcb_process,
    .transmitted = fcb_transmitted,
    .debug = fcb_debug,
    .report_error = fcb_report_error,
};

FakeClient fc_alloc(u_int8_t n_wires)
{
    FakeClient fc = calloc(sizeof(struct _FakeClient),1);
    fc->verbose = 1;
    fc->bus = hdl_alloc(fc, n_wires, &bcb);
    fc->socket_fd = -1;
    return fc;
}

void fc_free(FakeClient fc)
{
    if(fc->socket_fd > -1)
        close(fc->socket_fd);
    free(fc);
}

void fc_send(FakeClient fc, BusMessage msg, u_int8_t prio)
{
    hdl_send(fc->bus, msg, prio);
}

char fc_connect(FakeClient fc, const char *sockname)
{
    struct sockaddr_un address;
    int socket_fd;

    if(fc->socket_fd >= 0)
        return 0;
    
    socket_fd = socket(PF_UNIX, SOCK_STREAM, 0);
    memset(&address, 0, sizeof(struct sockaddr_un));
    address.sun_family = AF_UNIX;
    strncpy(address.sun_path, sockname, sizeof(address.sun_path)-1);
    if(connect(socket_fd, 
               (struct sockaddr *) &address, 
               sizeof(struct sockaddr_un)) != 0) {
        fprintf(stderr,"connect() failed\n");
        return 0;
    }
    fc->socket_fd = socket_fd;
    return 1;
}

char fc_process(FakeClient fc)
{
    u_int8_t c;
    switch(read(fc->socket_fd, &c, 1)) {
    case -1:
        perror("poll");
        close(fc->socket_fd);
        fc->socket_fd = -1;
        return 0;
    case 0:
        close(fc->socket_fd);
        fc->socket_fd = -1;
        return 0;
    case 1:
        if(fc->verbose) {
            fprintf(stderr,"WireIn %x: ",c);
            fflush(stdout);
        }
        fc->wire_in = c;
        hdl_wire(fc->bus, c);
        return 1;
    }
}

void fc_timer(FakeClient fc)
{
    fc->timeout = 0;
    hdl_timer(fc->bus);
}

int fc_timeout(FakeClient fc)
{
    if (fc->timeout == 0)
        return -1;

    if (fc->timeout == 1)
        return fc->timeout2;

    return fc->timeout1 * (fc->timeout-1);
}

static void fcb_set_timeout(void *ref, u_int16_t delay)
{
    FakeClient fc = (FakeClient)ref;
    fc->timeout = delay;
}

static void fcb_set_wire(void *ref, u_int8_t bits)
{
    FakeClient fc = (FakeClient)ref;
    if(fc->socket_fd < 0)
        return;
    if(write(fc->socket_fd, &bits, 1) != 1) {
        perror("write");
        close(fc->socket_fd);                           
        fc->socket_fd = -1;
    }
    if(fc->verbose)
        fprintf(stderr,"WireOut %x\n",bits);
}

static u_int8_t fcb_get_wire(void *ref)
{
    FakeClient fc = (FakeClient)ref;
    return fc->wire_in;
}

static char fcb_process(void *ref, BusMessage msg)
{
    FakeClient fc = (FakeClient)ref;
    if(fc->verbose)
        fprintf(stderr,"RCVD %d > %d (%d): %*s\n",msg->src,msg->dst,msg->code,msg_length(msg),msg_start(msg));
    fc->in_msg = msg;
}

static void fcb_transmitted(void *ref, BusMessage msg, enum HDL_RES result)
{
    FakeClient fc = (FakeClient)ref;
    fc->out_msg = msg;
    fc->out_result = result;
    if(fc->verbose)
        fprintf(stderr,"SENT %d > %d (%d): %*s\n",msg->src,msg->dst,msg->code,msg_length(msg),msg_start(msg));
}

static void fcb_debug(void *ref, const char *text, va_list arg)
{
    FakeClient fc = (FakeClient)ref;
    if (!fc->verbose)
        return;
    fprintf(stderr,"DEBUG ");
    vfprintf(stderr, text, arg);
    putc('\n',stderr);
}

static void fcb_report_error(void *ref, enum HDL_ERR err)
{
    FakeClient fc = (FakeClient)ref;
    fprintf(stderr,"ERROR %d\n",err);
}

u_int16_t cpu_random(u_int16_t x)
{
    return x>>4;
}
