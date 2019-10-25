#include "moatbus/message.h"
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <assert.h>
#include <string.h> // memcmp
#include "moatbus/crc.h"

//
// Test program for high-level CRC checks
//
// This progran tests whether a CRC over the resulting message is a useable
// way to recognize errors. Surprise: it is not. A single fault can fail
// both CRC-6 and CRC-11.
//
int gnf = 999;
int _C[] = {0,0,11,14,11,14,11};
int _X[] = {0,0,7,5,3,3,2};
u_int8_t bad[6][12] = {{0}};
unsigned long long skip0=0,skip1=0,skip2=0;

void run1(int N, int x, int nf) {
    //fprintf(stderr,"N=%d x=%d nf=%d\n",N,x,nf);
    u_int C=_C[N];
    u_int X=_X[N];
    u_int NN = ((1<<N)-1);
    u_int CC = ((1<<C)-1);
    u_int faults[nf];

    BusMessage msg=NULL;
    BusMessage mm = NULL;
    u_int8_t *m_out = NULL;

    if((bad[N][nf] != 0) && (bad[N][nf] <= x)) {
        x=bad[N][nf]-1;
        if (x<2) {
            skip0++;
            goto out;
        }
    }
    msg = msg_alloc(x);
    msg_start_send(msg);

    for(int xx=x;xx>0;--xx) {
        u_int8_t c = random()*256L/(RAND_MAX+1L);
        msg_send_data(msg,&c,1);
    }
    u_int nc = ((x+5)*8+C-1)/C; // 3 bytes header, 2 bytes CRC
    m_out = malloc(nc*X+5);
    m_out[0]=1;

    msg->src = random()*(128+4L)/(RAND_MAX+1L)-4;
    msg->dst = random()*(128+4L)/(RAND_MAX+1L)-4;
    msg->code = 2;
    msg_add_header(msg);

    u_int8_t msg_crc6(BusMessage m) {
        u_int8_t *data = msg_start(m);
        u_int8_t *data_end = data + msg_length(m);
        u_int8_t c6 = 0;
        for(; data < data_end; data++)
            c6 = crc6_update(c6, *data,8);
        return c6;
    }

    u_int16_t msg_crc11(BusMessage m) {
        u_int8_t *data = msg_start(m);
        u_int8_t *data_end = data + msg_length(m);
        u_int16_t c11 = 0;
        for(; data < data_end; data++)
            c11 = crc11_update(c11, *data,8);
        return c11;
    }

    if (0) // msg_bits(msg) <= 48) // without CRC
        msg_fill_crc(msg, C, msg_crc6(msg), 6);
    else
        msg_fill_crc(msg, C, msg_crc11(msg), 11);

    u_int16_t n = 0;
    msg_start_extract(msg);
    while (msg_extract_more(msg)) {
        u_int8_t b[X];
        u_int16_t x = msg_extract_chunk(msg,C);
        for (u_int i=X;i>0;) {
            b[--i] = x%NN;
            x /= NN;
        }
        for (u_int i=0;i<X;i++,n++)
            m_out[n+1] = m_out[n] ^ (b[i]+1);
    }

    unsigned int l1 = 0;
    unsigned int l2 = n;

    for(int f = 0; f < nf; f++) {
        int again;
        u_int fi;
        int pos;
        int bp;
        do {
            again=0;
            pos = l1+1+random()%((l2-l1-2)<<3);
            int bit = pos%N;
            pos >>= 3;
            bp = 1<<bit;
            fi = pos<<3 | bit;
            for(int fx=0;fx<f;fx++) {
                if (faults[fx] == fi)
                    again=1;
            }
            faults[f] = fi;
        } while(again);
        m_out[pos] ^= bp;
    }

    mm = msg_alloc(msg->data_max);
    msg_start_add(mm);
    u_int xx = 0;
    u_int16_t v = 0;
    u_int8_t c = m_out[0];
    for(int nn = 1; nn <= n; nn++) {
        int xc = c^m_out[nn];
        if (!xc) {
            // fault created zero-change transition
            skip1++;
            goto out;
        }
        v = v*NN+xc-1;
        c = m_out[nn];

        if(++xx == X) {
            if (v > CC) {
                // fault created too large result
                skip2++;
                goto out;
            }
            msg_add_chunk(mm,v,C);
            v=0; xx=0;
        }
    }

    char crc_ok;
    u_int16_t c_x;
    u_int16_t crc;
    if (0) { // msg_bits(mm) <= 58) {
        crc = msg_drop(mm, 6);
        msg_align(mm, msg_drop(mm, 1));
        crc_ok = (crc == (c_x = msg_crc6(mm)));
    } else {
        crc = msg_drop(mm, 11);
        msg_align(mm, msg_drop(mm, 1));
        crc_ok = (crc == (c_x = msg_crc11(mm)));
    }
    if (!nf) {
        assert(crc_ok);
        msg_read_header(mm);
        assert(msg_length(msg) == msg_length(mm));
        assert(!memcmp(msg_start(msg),msg_start(mm),msg_length(msg)));
        assert(mm->src == msg->src);
        assert(mm->dst == msg->dst);
        assert(mm->code == msg->code);
    } else if(crc_ok) {
        assert (memcmp(msg_start(msg),msg_start(mm),msg_length(msg)));
        // Owch
        int onf = bad[N][nf];
        if ((onf == 0) || (onf > x)) {
            printf("\r bad on N=%d/faults=%d, len=%d___________\n",N,nf,x);
            bad[N][nf] = x;
        }

    }
out:
    if (mm)
        msg_free(mm);
    if (msg)
        msg_free(msg);
    if (m_out)
        free(m_out);
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
    unsigned long long x = 0;
    for(int i=0;i<6;i++)
        for(int j=0;j<12;j++)
            bad[i][j]=0;
    irand();
    while(1) {
        x += 1;
        run1(random()%4+2,random()*32ULL/RAND_MAX + 2, random()%10+1);
//        run1(random()%4+2,random()*32ULL/RAND_MAX + 2, random()%3+1);
        if (!(x % 1000000)) {
            printf("\r %llu %llu %llu %llu", x,skip0,skip1,skip2);
            fflush(stdout);
            irand();
        }
    }
}
