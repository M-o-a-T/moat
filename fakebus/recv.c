#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <unistd.h>
#include <string.h>
#include <getopt.h>

#include "fakebus/client.h"

static struct option long_options[] = {
    {"socket", required_argument,  0, 's'},
    {"timeout",required_argument,  0, 't'},
    {"timerB", required_argument,  0, 'T'},
    {"dest",   required_argument,  0, 'D'},
    {"wires",  required_argument,  0, 'b'},
    {"verbose",no_argument,        0, 'v'},
    {0,         0,                 0,  0 }
};

/*
 * A short test program to send random wire states to the fake bus
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
    char verbose = 0;
    int n_wires = 3;

    FakeClient fc;
    int opt;

    while((opt = getopt(argc, argv, "b:C:D:s:S:t:T:v")) != -1) {
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

    while(1) {
        unsigned char c;
        struct pollfd p = {fc->socket_fd,POLLIN,0};
        switch(poll(&p,1,fc_timeout(fc))) {
        case -1:
            perror("poll");
            fc_free(fc);
            return 1;
        case 0:
            fc_timer(fc);
            break;
        case 1:
            fc_process(fc);
            break;
        }

        if(fc->in_msg) {
            printf("GotMsg %s\n", msg_info(fc->in_msg));
            msg_free(fc->in_msg);
            fc->in_msg = NULL;
        }
        if(fc->out_msg) {
            printf("SentMsg %d\n",fc->out_result);
            msg_free(fc->out_msg);
            fc->out_msg = NULL;
            break;
        }
    }
    fc_free(fc);
    return 0;
}
