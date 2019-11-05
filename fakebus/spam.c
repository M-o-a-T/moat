#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <getopt.h>
#include <unistd.h>
#include <string.h>

/*
 * A short test program to send random wire states to the fake bus
 */
static struct option long_options[] = {
    {"socket", required_argument,  0, 's'},
    {"timeout",required_argument,  0, 't'},
    {"wires",  required_argument,  0, 'b'},
    {"verbose",no_argument,        0, 'v'},
    {0,         0,                 0,  0 }
};

int main(int argc, char * const* argv)
{
    struct sockaddr_un address;
    int  socket_fd, nbytes;
    const char *sockname = "/tmp/moatbus";
    int opt;
    int timer;
    u_int8_t n_wires;
    char verbose;

    while((opt = getopt(argc, argv, "b:s:t:v")) != -1) {
        switch (opt) {
        case 's':
            sockname = optarg;
            break;
        case 'b':
            n_wires = atoi(optarg);
            break;
        case 't':
            timer = atoi(optarg);
            break;
        case 'v':
            verbose = 1;
            break;
        default: /* '?' */
            fprintf(stderr, "Usage: %s\n        [-C # -D # -S # -s /path/to/socket -t timeA -T timeB -v ] data\n",
                    argv[0]);
            exit(2);
        }
    }

    socket_fd = socket(PF_UNIX, SOCK_STREAM, 0);
    if(socket_fd < 0)
    {
        printf("socket() failed\n");
        return 1;
    }

    /* start with a clean address structure */
    memset(&address, 0, sizeof(struct sockaddr_un));

    address.sun_family = AF_UNIX;
    strcpy(address.sun_path, sockname);

    if(connect(socket_fd, 
               (struct sockaddr *) &address, 
               sizeof(struct sockaddr_un)) != 0)
    {
        printf("connect() failed\n");
        return 1;
    }

    while(1) {
        unsigned char c;
        struct pollfd p = {socket_fd,POLLIN,0};
        switch(poll(&p,1,timer+rand()/(1+RAND_MAX/timer))) {
        case -1:
            perror("poll");
            close(socket_fd);
            return 1;
        case 0:
            c = 1<<(rand()%(1<<n_wires));
            write(socket_fd, &c, 1);
            break;
        case 1:
            switch(read(socket_fd, &c, 1)) {
            case -1:
                perror("poll");
                close(socket_fd);
                return 1;
            case 0:
                close(socket_fd);
                return 0;
            case 1:
                printf("%02x ",c);
                fflush(stdout);
                break;
            }
        }
    }
    close(socket_fd);
    return 0;
}
