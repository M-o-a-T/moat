#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <unistd.h>
#include <string.h>

int main(int argc, const char *argv[])
{
    struct sockaddr_un address;
    int  socket_fd, nbytes;
    char buffer[256];

    socket_fd = socket(PF_UNIX, SOCK_STREAM, 0);
    if(socket_fd < 0)
    {
		printf("socket() failed\n");
		return 1;
    }

    /* start with a clean address structure */
    memset(&address, 0, sizeof(struct sockaddr_un));

    address.sun_family = AF_UNIX;
    strcpy(address.sun_path, (argc>1) ? argv[1] : "/tmp/moatbus");

    if(connect(socket_fd, 
               (struct sockaddr *) &address, 
               sizeof(struct sockaddr_un)) != 0)
    {
		printf("connect() failed\n");
		return 1;
    }

	while(1) {
		unsigned char c;
		struct pollfd p = {socket_fd,POLLIN};
		switch(poll(&p,1,1000+rand()/(1+RAND_MAX/1000))) {
		case -1:
			perror("poll");
    		close(socket_fd);
			return 1;
		case 0:
			c = 1<<(rand()%8);
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
