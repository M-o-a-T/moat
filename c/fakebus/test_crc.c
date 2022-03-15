#include "moatbus/crc.h"
#include "moatbus/message.h"
#include <stdio.h>
#include <fcntl.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/stat.h>
#include <assert.h>
#include <string.h> // memcmp


//#define CRC_SIZE 11
#define DATA_SIZE 8

unsigned char CRC_SIZE;

u_int16_t bad[16]; // max

typedef u_int16_t crc_t;

crc_t poly;
crc_t *table;
u_int *faults;
u_int8_t data[65536/8];

crc_t CRC_ADD(crc_t crc, u_int8_t val)
{
    return table[(crc ^ val) & ((1<<DATA_SIZE)-1)] ^ (crc>>DATA_SIZE);
}
crc_t _bytecrc_r(crc_t crc, crc_t poly)
{
    for(u_int i = 0; i < DATA_SIZE; i++)
        crc = (crc & 1) ? (crc >> 1) ^ poly : crc>>1;
    return crc;
}

void _mktable()
{
    table = malloc(sizeof(crc_t)*(1<<DATA_SIZE));
    for(u_int i = 0; i < (1<<DATA_SIZE); i++)
        table[i] = _bytecrc_r(i, poly);
}

#define ALL(_i)    for(u_int _i=0; _i < datalen/DATA_SIZE+1; _i++)
int check(unsigned int n_faults, const char **args)
{
    u_int datalen = 0;
    for(unsigned int d = 0; d < n_faults; d++) {
        u_int off = strtol(args[d],NULL,10);
        if(datalen < off)
            datalen = off;
    }

    memset(data,0,datalen/DATA_SIZE+1);
    for(unsigned int d = 0; d < n_faults; d++) {
        u_int off = strtol(args[d],NULL,10);
        data[off/DATA_SIZE] ^= 1<<(off%DATA_SIZE);
    }
    
    crc_t crc=0;
    ALL(i) crc = CRC_ADD(crc,data[i]);
    printf("CRC=x%x\n",crc);
    return crc;
}

void run(u_int datalen, u_int n_faults, char big)
{
    if (big && !bad[n_faults])
        n_faults -= 1;
    if (bad[n_faults] && bad[n_faults] <= datalen)
        datalen = bad[n_faults]-1;
    if (datalen < n_faults+2)
        goto out;

    u_int8_t *data = alloca(datalen/DATA_SIZE+3);
    // a CRC is all about XOR, thus it doesn't depend on the actual data
    // so we zero the memory, which is fast, and note that the CRC of zero
    // is zero, thus we only need to calculate it once

    //ALL(i) data[i] = random()&DATA_MASK;
    memset(data,0,datalen/DATA_SIZE+1);
    data[0]=1;
    faults[0]=0;

    // generate and inject faults
    for(u_int f = 1; f < n_faults; f++) {
        int again;
        u_int pos;
        do {
            again=0;
            pos = ((unsigned long int)random())%datalen;
            for(u_int fx=0;fx<f;fx++) {
                if (faults[fx] == pos) {
                    again=1;
                    break;
                }
            }
        } while(again);

        faults[f] = pos;
        data[pos/DATA_SIZE] ^= 1<<(pos%DATA_SIZE);
    }

    crc_t crc=0;
    ALL(i) crc = CRC_ADD(crc,data[i]);

    if(!crc) {
        u_int16_t dmin=0xffff,dmax=0;
        for(u_int f = 0; f < n_faults; f++) {
            u_int c=faults[f];
            if(dmin>c) dmin=c;
            if(dmax<c) dmax=c;
        }
        bad[n_faults] = dmax-dmin+1;
#if 0
        if(n_faults == 4)
            printf("NF %x: %d %d %d %d             \n", poly, faults[0]-dmin,faults[1]-dmin,faults[2]-dmin,faults[3]-dmin);
#endif
    }
out:;
    //free(data);
    //free(faults);
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

int main(int argc, const char *argv[]) {
    if(argc < 3) {
        fprintf(stderr,"Usage: %s bits hexpoly\n",argv[0]);
        exit(2);
    }
    CRC_SIZE=strtol(argv[1],NULL,10);
    poly=strtol(argv[2],NULL,16);
    faults = malloc(CRC_SIZE*sizeof(u_int));
    if((poly <= 0) || ((poly & ((1<<CRC_SIZE)-1)) != poly)) {
        fprintf(stderr,"Polynomial too large.\n");
        exit(2);
    }
    _mktable();
    if(argc > 3)
        return check(argc-3,argv+3);
    char big = 0;
    memset(bad,0,16*2);
    unsigned long long x = 0;
    for(int j=0;j<CRC_SIZE;j++)
        bad[j]=0;
    irand();
    while(1) {
        x += 1;
        run((random()&0xffff)+2, ((random()%(CRC_SIZE-2)))+2, big);
        if (!(x % 100000)) {
            printf("    %llu ", x);
            for(u_int i=2; i<CRC_SIZE;i++)
                printf("%4d ",bad[i]);
            printf("  %x             \r",poly);
            fflush(stdout);
            irand();
            //if (x>=10000000)
                //big = 1;
        }
    }
}
