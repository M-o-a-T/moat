#include "moatbus/crc.h"
#include "moatbus/message.h"
#include <stdio.h>
#include <fcntl.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/stat.h>
#include <assert.h>
#include <string.h> // memcmp

u_int8_t bad[12];

void run(u_int datalen, u_int n_faults) {
    u_int8_t *data = alloca(datalen);
    u_int *faults = alloca(n_faults);

    if (bad[n_faults] && bad[n_faults]<=datalen) {
        datalen = bad[n_faults]-1;
        if (datalen < 2)
            return;
    }
#define ALL(_i)    for(u_int _i=0; _i < datalen; _i++)
    ALL(i) data[i] = random()*256L/(RAND_MAX+1L);

    u_int16_t crc=0;
    ALL(i) crc = crc8_update(crc,data[i]);

    // inject faults
    for(u_int f = 0; f < n_faults; f++) {
        int again;
        u_int pos;
        do {
            again=0;
            pos = random()%(datalen*8L);
            for(u_int fx=0;fx<f;fx++) {
                if (faults[fx] == pos)
                    again=1;
            }
        } while(again);

        faults[f] = pos;
        data[pos>>3] ^= 1<<(pos&7);
    }

    u_int16_t crc2=0;
    ALL(i) crc2 = crc8_update(crc2,data[i]);

    if (n_faults == 0) {
        assert(crc == crc2);
    } else if(crc == crc2) {
        // Owch
        void mpr() {
            u_int16_t cr;
            u_int8_t cx;
            ALL(i)
                printf(" %02x",data[i]);
            printf("\n");
            ALL(i) {
                cr=crc8_update(cr,data[i]);
                printf("  %02x %02x", data[i],cr);
                if(!((i+1)%8))
                    printf("\n");
            }
            printf("\n");
        }

        bad[n_faults] = datalen;
        printf("\r bad on faults=%d, len=%d___________\n",n_faults,datalen);
        bad[n_faults] = datalen;
        for(u_int n=n_faults+1;n<12;n++)
            if (!bad[n] || bad[n] > datalen)
                bad[n] = datalen;
        if(n_faults == 2) {
            mpr();
            printf("Fail:");
            for(u_int f = 0; f < n_faults; f++) {
                u_int pos = faults[f];
                printf(" %d/%d",pos>>3,pos&7);
                data[pos>>3] ^= 1<<(pos&7);
            }
            printf("\n");
            mpr();
        }
    }
}

void irand() {
    static int fd = -1;
    unsigned int seed;
    if(fd==-1)
        fd=open("/dev/urandom",O_RDONLY);
    if(read(fd,&seed,sizeof(seed)) != sizeof(seed)) {
        perror("rand");
        exit(1);
    }
    srandom(seed);
}

int main() {
    memset(bad,0,sizeof(bad));
    unsigned long long x = 0;
    for(int j=0;j<12;j++)
	bad[j]=0;
    irand();
    while(1) {
        x += 1;
        run((random()&0x1F)+2,(random()&7)+1);
        if (!(x % 1000000)) {
            printf("\r %llu", x);
            fflush(stdout);
            irand();
        }
    }
}
