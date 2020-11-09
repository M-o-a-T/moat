#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <unistd.h>
#include <string.h>
#include <getopt.h>
#include <time.h>

#include "fakebus/client.h"

static struct option long_options[] = {
    {"socket", required_argument,  0, 's'},
    {"timeout",required_argument,  0, 't'},
    {"timerB", required_argument,  0, 'T'},
    {"source", required_argument,  0, 'S'},
    {"dest",   required_argument,  0, 'D'},
    {"cmd",    required_argument,  0, 'C'},
    {"n_msg",  required_argument,  0, 'n'},
    {"n_delay",required_argument,  0, 'N'},
    {"wires",  required_argument,  0, 'b'},
    {"verbose",no_argument,        0, 'v'},
    {0,         0,                 0,  0 }
};

/*
 * A short test program to send a message to the fake bus
 */
int main(int argc, char* const* argv)
{
    struct sockaddr_un address;
    int  socket_fd, nbytes;
    char buffer[256];

    const char *sockname = "/tmp/moatbus";
    int timerA = 10;
    int timerB = 5;
    int src = 1;
    int dest = 2;
    int cmd = 0;
    int n_msg = 1;
    int n_delay = 5;
    char has_fc_timer = 0;
    char verbose = 0;
    int n_wires = 3;

    FakeClient fc;
    int opt;

    while((opt = getopt(argc, argv, "b:C:D:n:N:s:S:t:T:v")) != -1) {
        switch (opt) {
        case 's':
            sockname = optarg;
            break;
        case 'b':
            n_wires = atoi(optarg);
            break;
        case 'C':
            cmd = atoi(optarg);
            break;
        case 'D':
            dest = atoi(optarg);
            break;
        case 'n':
            n_msg = atoi(optarg);
            break;
        case 'N':
            n_delay = atof(optarg);
            break;
        case 'S':
            src = atoi(optarg);
            break;
        case 't':
            timerA = atoi(optarg);
            break;
        case 'T':
            timerB = atoi(optarg);
            break;
        case 'v':
            verbose++;
            break;
        default: /* '?' */
            fprintf(stderr, "Usage: %s\n        [-C # -D # -S # -s /path/to/socket -t timeA -T timeB -v ] data\n",
                    argv[0]);
            exit(2);
        }
    }

    fc = fc_alloc(n_wires);
    fc->timeout1 = timerA;
    fc->timeout2 = timerB;
    fc->verbose = verbose;
    
    if(!fc_connect(fc, sockname))
        return 1;

    const char *arg = argv[optind];
    if (arg == NULL)
        arg = "!";

    void msg_send() {
        BusMessage msg = msg_alloc(strlen(arg));
        msg->src = src;
        msg->dst = dest;
        msg->code = cmd;
        msg_start_send(msg);
        msg_add_data(msg,arg,strlen(arg));
        fc_send(fc, msg);
    }

    time_t t1 = time(NULL)-n_delay;

    int timeout() {
        int t = time(NULL)-t1;
        int f = fc_timeout(fc);
        has_fc_timer=(f>0);
        if (t>n_delay)
            return 0;
        t = (n_delay-t)*1000;
        if (f < 0)
            return t;
        return (f<t)?f:t;
    }

    while(1) {
        unsigned char c;
        struct pollfd p = {fc->socket_fd,POLLIN,0};
        switch(poll(&p,1,timeout())) {
        case -1:
            perror("poll");
            fc_free(fc);
            return 1;
        case 0:
            if(time(NULL)-t1 > n_delay) {
                t1=time(NULL);
                msg_send();
            }
            if(has_fc_timer)
                fc_timer(fc);
            break;
        case 1:
            fc_process(fc);
            break;
        }

        if(fc->in_msg) {
            printf("Got %s\n",msg_info(fc->in_msg));
            msg_free(fc->in_msg);
            fc->in_msg = NULL;
        }
        if(fc->out_msg) {
            printf("Sent %s %d\n",arg,fc->out_result);
            msg_free(fc->out_msg);
            fc->out_msg = NULL;
            if(!--n_msg)
                break;
        }
    }
    fc_free(fc);
    return 0;
}
