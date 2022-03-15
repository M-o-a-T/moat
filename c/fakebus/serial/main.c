#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <unistd.h>
#include <string.h>
#include <getopt.h>

#include "fakebus/client.h"
#include "moatbus/serial.h"

static struct option long_options[] = {
    {"socket", required_argument,  0, 's'},
    {"timeout",required_argument,  0, 't'},
    {"timerB", required_argument,  0, 'T'},
    {"wires",  required_argument,  0, 'b'},
    {"verbose",no_argument,        0, 'v'},
    {0,         0,                 0,  0 }
};

static void errs(SerBus sb)
{
    fprintf(stderr, "Exiting.\n");
    if(sb->err_overflow) fprintf(stderr, "Overflow %d",sb->err_overflow);
    if(sb->err_lost) fprintf(stderr, "Lost %d",sb->err_lost);
    if(sb->err_spurious) fprintf(stderr, "Spurious %d",sb->err_spurious);
    if(sb->err_crc) fprintf(stderr, "CRC %d",sb->err_crc);
}

/*
 * A test program to adapt our fakebus to messages via stdin/stdout.
 */
int main(int argc, char* const* argv)
{
    struct sockaddr_un address;
    int  socket_fd, nbytes;
    char buffer[256];

    const char *sockname = "/tmp/moatbus";
    int timerA = 10;
    int timerB = 5;
    char verbose = 0;
    int n_wires = 3;

    FakeClient fc;
    SerBus sb;

    int opt;
    int16_t sb_out = -1;

    while((opt = getopt(argc, argv, "b:s:t:T:v")) != -1) {
        switch (opt) {
        case 's':
            sockname = optarg;
            break;
        case 'b':
            n_wires = atoi(optarg);
            break;
        case 't':
            timerA = atoi(optarg);
            break;
        case 'T':
            timerB = atoi(optarg);
            break;
        case 'v':
            verbose = 1;
            break;
        default: /* '?' */
            fprintf(stderr, "Usage: %s\n        [-s /path/to/socket -t timeA -T timeB -v ]\n",
                    argv[0]);
            exit(2);
        }
    }

    fc = fc_alloc(n_wires);
    fc->timeout1 = timerA;
    fc->timeout2 = timerB;
    fc->verbose = verbose;

    sb = sb_alloc();
    
    if(!fc_connect(fc, sockname))
        return 1;

    while(1) {
        unsigned char c;
        struct pollfd p[3] = {{fileno(stdin),POLLIN,0},{fc->socket_fd,POLLIN,0},{fileno(stdout),POLLOUT,0}};
        switch(poll(p,2+(sb_out>=0),fc_timeout(fc))) {
        case -1:
            goto err;
        case 0:
            fc_timer(fc);
            sb_idle(sb);
            break;
        default:
            if(p[1].revents)
                fc_process(fc);

            if(p[0].revents) {
                u_int8_t c;
                if(read(fileno(stdin),&c,1) != 1)
                    goto err;
                sb_byte_in(sb, c);
            }
            if(p[2].revents) {
                u_int8_t c = sb_out;
                sb_out = -1;
                if(write(fileno(stdout),&c,1) != 1)
                    goto err;
            }
            break;
        }

        if(fc->in_msg) {
            fprintf(stderr,"GotMsg\n");
            BusMessage m = fc->in_msg;
            fc->in_msg = NULL;
            sb_send(sb,m);
        }
        if(fc->out_msg) {
            fprintf(stderr,"SentMsg %d\n",fc->out_result);
            msg_free(fc->out_msg);
            fc->out_msg = NULL;
        }
        if(sb_out == -1)
            sb_out = sb_byte_out(sb);

        BusMessage m = sb_recv(sb);
        if (m != NULL)
            fc_send(fc, m);
    }
    errs(sb);
    fc_free(fc);
    sb_free(sb);
    return 0;
err:
    errs(sb);
    fc_free(fc);
    sb_free(sb);
    return 1;
}
