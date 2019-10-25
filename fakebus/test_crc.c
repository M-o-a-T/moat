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
//#define DATA_SIZE 4
//#define POLY 0x583
//#define POLY 0x64d
//
#define CRC_SIZE 11
#define DATA_SIZE 8

u_int16_t bad[CRC_SIZE];

#define DATA_MASK ((1<<DATA_SIZE)-1)
#if CRC_SIZE <= 8
typedef u_int8_t crc_t;
#define CRC_N ((CRC_SIZE>4)?2:1)
#else // CRC_SIZE >8
typedef u_int16_t crc_t;
#define CRC_N ((CRC_SIZE>12)?4:3)
#endif

crc_t poly;
crc_t *table;
crc_t CRC_ADD(crc_t crc, u_int8_t val)
{
    return table[(crc ^ val) & ((1<<DATA_SIZE)-1)] ^ (crc>>DATA_SIZE);
}
crc_t _bitrev(u_int x, u_int sz) {
    crc_t y = 0;
    for(u_int i = 0; i < sz; i++) {
        y = (y << 1) | (x & 1);
        x >>= 1;
    }
    return y;
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


void run(u_int datalen, u_int n_faults)
{
    u_int8_t *data = alloca(datalen/DATA_SIZE+3);
    u_int *faults = alloca(n_faults*sizeof(u_int));

    if (bad[n_faults] && bad[n_faults] <= datalen)
        datalen = bad[n_faults]-1;
    if (datalen < n_faults+2)
        goto out;
#define ALL(_i)    for(u_int _i=0; _i < datalen/DATA_SIZE+1; _i++)
    ALL(i) data[i] = random()&DATA_MASK;

    crc_t crc=0;
    ALL(i) crc = CRC_ADD(crc,data[i]);

    // inject faults
    for(u_int f = 0; f < n_faults; f++) {
        int again;
        u_int pos;
        do {
            again=0;
            pos = ((unsigned long int)random())%datalen;
            for(u_int fx=0;fx<f;fx++) {
                if (faults[fx] == pos)
                    again=1;
            }
        } while(again);

        faults[f] = pos;
        data[pos/DATA_SIZE] ^= 1<<(pos%DATA_SIZE);
    }

    crc_t crc2=0;
    ALL(i) crc2 = CRC_ADD(crc2,data[i]);

    if (n_faults == 0) {
        assert(crc == crc2);
    } else if(crc == crc2) {

        //printf("\r bad on faults=%d, len=%d___________\n",n_faults,datalen);
        u_int16_t dmin=0xffff,dmax=0;
        for(u_int f = 0; f < n_faults; f++) {
            u_int c=faults[f];
            if(dmin>c) dmin=c;
            if(dmax<c) dmax=c;
        }

        bad[n_faults] = dmax-dmin+1;
//      for(u_int n=n_faults+1; n<sizeof(bad)/sizeof(bad[0]) ;n++)
//          if (!bad[n] || bad[n] > datalen)
//              bad[n] = datalen;
#if 0
        // Owch
        void mpr() {
            crc_t cr = 0;
            ALL(i)
                printf(" %02x",data[i]);
            printf("\n");
            ALL(i) {
                cr=CRC_ADD(cr,data[i]);
                printf("  %02x %*x", data[i],CRC_N,cr);
                if(!((i+1)%8))
                    printf("\n");
            }
            printf("\n");
        }
        if(n_faults == 4) {
            printf("\nFail vector for %d:", datalen);
            for(u_int f = 0; f < n_faults; f++) {
                u_int pos = faults[f];
                printf(" %d/%d", pos/DATA_SIZE, pos%DATA_SIZE);
            }
            printf("\n");
            mpr();
            u_int16_t k=faults[n_faults-1];
            for(u_int f = 0; f < n_faults; f++) {
                u_int pos = faults[f];
                assert (k == faults[n_faults-1]);
                data[pos/DATA_SIZE] ^= 1<<(pos%DATA_SIZE);
                assert (k == faults[n_faults-1]);
            }
            mpr();
        }
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
    if(argc != 2) {
        fprintf(stderr,"Usage: %s hexpoly\n",argv[0]);
        exit(2);
    }
    poly=strtol(argv[1],NULL,16);
    if((poly <= 0) || ((poly & ((1<<CRC_SIZE)-1)) != poly)) {
        fprintf(stderr,"Polynomial too large.\n");
        exit(2);
    }
    _mktable();
    memset(bad,0,sizeof(bad));
    unsigned long long x = 0;
    for(int j=0;j<CRC_SIZE;j++)
        bad[j]=0;
    irand();
    while(1) {
        x += 1;
        run((random()&0xffff)+2, ((random()%(CRC_SIZE-2)))+2);
        if (!(x % 100000)) {
            printf("    %llu ", x);
            for(u_int i=2; i<sizeof(bad)/sizeof(bad[0]);i++)
                printf("%4d ",bad[i]);
            printf("  %x             \r",poly);
            fflush(stdout);
            irand();
        }
    }
}
