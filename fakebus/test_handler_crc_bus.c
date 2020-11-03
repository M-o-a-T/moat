#include "moatbus/crc.h"
#include "fakebus/crc11.h"
#include "moatbus/message.h"
#include <stdio.h>
#include <fcntl.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/stat.h>
#include <assert.h>
#include <string.h> // memcmp

int gnf = 999;
int _C[] = {0,0,11,14,11,14,11};
int _X[] = {0,0,7,5,3,3,2};
u_int8_t bad[6][12] = {{0}};
unsigned long long skip0=0,skip1=0,skip2=0;

#define C6 1

char run1(u_int N, u_int datalen, u_int n_faults) {
    u_int C=_C[N];
    u_int X=_X[N];
    u_int NN = ((1<<N)-1);
    u_int CC = ((1<<C)-1);
    u_int faults[n_faults];
    char res=0;

    //printf("Run\n");
    BusMessage msg=NULL;
    BusMessage mm = NULL;
    u_int8_t *m_out = NULL;

    if(bad[N][n_faults] && (bad[N][n_faults] <= datalen+1)) {
        datalen=bad[N][n_faults]-1;
        if (datalen==0) {
            skip0++;
            goto out;
        }
    }

    /////// WRITER ///////

    msg = msg_alloc(datalen);
    msg_start_send(msg);
    for(int xx=datalen;xx>0;--xx) {
        u_int8_t c = random()*256L/(RAND_MAX+1L);
        msg_add_data(msg,&c,1);
    }
    u_int nc = ((datalen+5)*8+C-1)/C; // 3 bytes header, 1 frame CRC
    m_out = malloc(nc*X+5);
    m_out[0]=0; // TODO

    msg->src = -1;//random()*(128+4L)/(RAND_MAX+1L)-4;
    msg->dst = -2;//random()*(128+4L)/(RAND_MAX+1L)-4;
    msg->code = 2;
    msg_add_header(msg);
    u_int16_t msg_len = msg_length(msg);
    msg_fill_crc(msg,C,0,(C6&&(msg_bits(msg)<=48))?6:11); // without CRC.
    // 48+1+6 = 55 = 5 frames / 11 bits < 56 = 4 frames / 14 bits.

    for(int rep=0;rep<2;rep++) {
    u_int16_t n = 0, n_p = 0;
    u_int16_t crc11 = 0;
    u_int16_t v_p = 0, cb = m_out[0];

    // extract message (plus empty CRC at end)
    msg_start_extract(msg);
        u_int8_t b[X];
    while (msg_extract_more(msg)) {
        n_p = n;

        //u_int8_t b[X];
        u_int16_t v = msg_extract_chunk(msg,C);
        v_p = v;
        //printf("E:%03x\n",v);
        for (u_int i=X;i>0;) {
            b[--i] = v%NN +1;
            v /= NN;
        }
        for (u_int i=0; i<X; i++) {
            cb ^= b[i];
            crc11 = crc11_update(crc11, cb ^ m_out[0],N);
            m_out[++n] = cb;
        }
    }
    // replace last block with "real" CRC
    v_p |= crc11;
    n = n_p;
    {
        u_int16_t x = v_p;
        u_int8_t bb[X];
        u_int8_t cb = m_out[n];
        //printf("EC:%03x (%02x @%d)\n\n",x,cb,n);
        for (u_int i=X;i>0;) {
            b[--i] = x%NN +1;
            x /= NN;
        }
        for (u_int i=0; i<X; i++) {
            cb ^= b[i];
            m_out[++n] = cb;
        }
    }
    if(rep) {
        printf("n_p %d, n %d, last %x\nmsg:",n_p,n,v_p);
        for(u_int i=0;i<=n;i++)
            printf(" %02x",m_out[i]);
        printf(" --");
        for(u_int i=0;i<X;i++)
            printf(" %02x",b[i]);
        printf("\n");
        goto out;
    }

    // inject faults
    for(u_int f = 0; f < n_faults; f++) {
        int again;
        u_int fi;
        int pos;
        int bp;
        do {
            again=0;
            pos = random()%((n_p-1)<<3);
            int bit = pos%N;
            pos = (pos >> 3) +1;
            bp = 1<<bit;
            fi = pos<<3 | bit;
            // don't cancel a fault
            for(u_int fx=0;fx<f;fx++) {
                if (faults[fx] == fi)
                    again=1;
            }
            faults[f] = fi;
            assert (fi != 0);
        } while(again);
        m_out[pos] ^= bp;
    }

    /////// READER ///////

    // extract into new message
    mm = msg_alloc(msg->data_max);
    msg_start_add(mm);
    u_int xx = 0;
    u_int16_t v = 0;
    u_int8_t c = m_out[0];

    u_int8_t cn6 = 0, cn6_p = 0, cn6_pp = 0;
    u_int16_t cn11 = 0, cn11_p = 0, cn11_pp = 0;
    u_int16_t nv_p = 0, nn_p = 0, nn_pp = 0;

    for(int nn = 1; nn <= n; nn++) {
        int xc = c^m_out[nn];
        if (!xc) {
            skip1++;
            goto out;
        }
        v = v*NN+xc-1;
        c = m_out[nn];  // or: c ^= xc
        cn11 = crc11_update(cn11, c ^ m_out[0],N);

        if(++xx == X) {
            nn_p = nn_pp; nn_pp = nn;
            //printf("D:%03x\n",v);
            if (v > CC) {
                skip2++;
                goto out;
            }
            cn6_p = cn6_pp; cn6_pp = cn6;
            cn11_p = cn11_pp; cn11_pp = cn11;
            nv_p = v;
            msg_add_chunk(mm,v,C);
            v=0; xx=0;
        }
    }
    assert(xx==0);

    // zero the CRC value, recreate last frame, add it to CRC
    {
        u_int16_t x = nv_p;
        //u_int8_t b[X];
        u_int8_t c = m_out[nn_p];
        //printf("DC:%03x (%02x @%d) b-%d\n",x,c,nn_p,msg_bits(msg));
        if (C6 && (msg_bits(msg) <= 56)) // with CRC
            x &=~((1<<6)-1);
        else
            x &=~((1<<11)-1);
        for (u_int i=X;i>0;) {
            b[--i] = x%NN+1;
            x /= NN;
        }
        for (u_int i=0;i<X;i++) {
            c ^= b[i];
            cn11_p = crc11_update(cn11_p, c ^ m_out[0],N);
        }
    }

    // retrieve and compare CRC
    char crc_ok;
    u_int8_t m6 = 0;
    u_int16_t m11 = 0;
    if (C6 && (msg_bits(mm) <= 56)) // with CRC
        crc_ok = (cn6_p == (m6 =msg_drop(mm, 6)));
    else
        crc_ok = (cn11_p == (m11 =msg_drop(mm, 11)));
    // this depends on frame size <16
    msg_align(mm, msg_drop(mm, 1));

    if (n_faults == 0) {
        assert(crc_ok);
        msg_read_header(mm);
        if(msg_len != msg_length(mm)) {
        msg_read_header(mm);
        }
        assert(!memcmp(msg_start(msg),msg_start(mm),msg_len));
        assert(mm->src == msg->src);
        assert(mm->dst == msg->dst);
        assert(mm->code == msg->code);
    } else if(crc_ok) {
        msg_read_header(mm);
        if(msg_len+msg->hdr_len == msg_length(mm))
            assert(memcmp(msg_start(msg)-msg->hdr_len,msg_start(mm)-mm->hdr_len,msg_len+msg->hdr_len));
            
        // Owch
        u_int onf = bad[N][n_faults];

        if ((onf == 0) || (onf-1 > datalen)) {
            printf("\r bad on N=%d/faults=%d, len=%d, crc %03x___________\n",N,n_faults,datalen,m11|m6);
            bad[N][n_faults] = datalen+1;
        }
        res=1;
#if 0
        void mpr() {
            u_int16_t cr;
            u_int8_t cx;
            char f = (n*N <= 58);
            for(int i=0;i<=n;i++)
                printf(" %02x",m_out[i]);
            printf("\n");
            for(int i=0;i<=n;i++) {
                if (i == 0) {
                    cr=0;
                    cx=m_out[0];
                    continue;
                }
                cr=f ? crc6_update(cr,m_out[i]^cx,N) : crc11_update(cr,m_out[i]^cx,N);
                printf("  %*x %03x",(N>4)?2:1, m_out[i],cr);
                if(!(i%8))
                    printf("\n");
            }
            printf("\n");
        }

        //if(n_faults == 2)
        {
            printf("nn_p %d last %x\nmm :", nn_p,nv_p);
            mpr();

            printf(" --");
            for(u_int i=0;i<X;i++)
                printf(" %02x",b[i]);
            printf("\nFail:");
            for(u_int f = 0; f < n_faults; f++) {
                u_int fi;
                int pos;
                int bp;
                fi = faults[f];
                pos = (fi >> 3);
                bp = 1<<(fi&7);
                m_out[pos] ^= bp;
                printf(" %d/%d",pos,fi&7);
            }
            printf("\nn_p %d, n %d, last %x\nmsg:",n_p,n,v_p);
            mpr();
            continue;
        }
#endif
    }
    goto out;
    }
out:
    if (mm)
        msg_free(mm);
    if (msg)
        msg_free(msg);
    if (m_out)
        free(m_out);
    return res;
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
        run1(random()%4+2,random()%100, 2);//random()%6);
        //if(run1(3,2,2)) return 0;
        //run1(3,2,0);
        if (!(x % 1000000)) {
            printf("\r %llu %llu %llu %llu", x,skip0,skip1,skip2);
            fflush(stdout);
            irand();
        }
    }
}
