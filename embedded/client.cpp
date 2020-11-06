#include "embedded/client.h"
#include "embedded/timer.h"
#include "embedded/main.h"
#include "embedded/logger.h"
#include "embedded/machine.h"
#include "moatbus/util.h"
#include <memory.h>
#include <stdlib.h>

static struct mtick addr_poll NO_INIT;
u_int8_t my_addr;

enum _AS {
    AS_GET_OK = 0,
    AS_GET_DELAY = 1,
    AS_GET_START = 10,
    AS_GET_END = 15,
} addr_state NO_INIT;

#ifdef DEBUG_ADDR
#define logger_addr logger
#else
#define logger_addr(s, ...) do {} while(0)
#endif

static void send_serial(int8_t dst, u_int8_t code, u_int8_t flag, u_int8_t timer) {
    u_int8_t len = cpu_serial_len-1;
    ASSERT(len<0x10);
    if (timer)
        flag |= 0x80;
    if (flag)
        len |= 0x10;
    BusMessage m = msg_alloc(cpu_serial_len+3);

    msg_start_send(m);
    msg_add_char(m, len);
    msg_add_data(m, cpu_serial, cpu_serial_len);
    if (flag)
        msg_add_char(m, flag);
    if (timer) 
        msg_add_char(m, timer);
    m->src = (my_addr == 0xff) ? -4 : my_addr;
    m->dst = dst;
    m->code = code;
    send_msg(m);
}

bool get_addr(MTICK _)
{
    if(addr_state == AS_GET_OK)
        return TRUE;
    if(addr_state == AS_GET_START) {
        // more random delay
        addr_state = (enum _AS)((u_int8_t)addr_state+1);
#ifndef DEBUG_ADDR
        u_int8_t mf;
        mf_set(&addr_poll.mf, mf = mf_random(1*MINI_F, 5*MINI_F));
        return TRUE;
#endif
    }
    if (addr_state <= AS_GET_END) {
        send_serial(-4,0,0,0);

        // schedule retry
#ifdef DEBUG_ADDR
        mf_set(&addr_poll.mf, 36); // 10 seconds
#else
        mf_set(&addr_poll.mf, mf_random((addr_state-AS_GET_START)*10*MINI_F, (addr_state-AS_GET_START)*30*MINI_F));
#endif
        if (addr_state < AS_GET_END)
            addr_state = (enum _AS)((u_int8_t)addr_state+1);
        else
            mf_stop(&addr_poll.mf);
        return TRUE;
    }
    if (addr_state == AS_GET_DELAY) {
        addr_state = AS_GET_OK;
        mf_stop(&addr_poll.mf);
        setup_addr_done();
        return TRUE;
    }
    return TRUE; // noop but keep the ticker
}

IN_C void setup_addr()
{
    my_addr = 0xFF;
}

IN_C void setup_get_addr()
{
    addr_state = AS_GET_START;
    mtick_init(&addr_poll, get_addr);
#ifdef DEBUG_ADDR
    mf_set(&addr_poll.mf, MINI_F); // 1 sec
#else
    u_int8_t mf;
    mf_set(&addr_poll.mf, mf_random(2*MINI_F, 15*MINI_F));
#endif
}

static char process_control_addr_assign(BusMessage msg, u_int8_t *data, msglen_t len)
{
    if (len < cpu_serial_len+1) {
        logger_addr("short1 %d",len);
        return 0;
    }
    if((*data & 0x0F) != cpu_serial_len-1) {
        logger_addr("len %d %d",*data & 0x0F, cpu_serial_len-1);
        return 0;
    }

    if(memcmp(data+1,cpu_serial,cpu_serial_len)) {
        logger_addr("wrong serial");
#if 0
        u_int8_t i;
        for(i=0;i<cpu_serial_len;i++)
            logger_addr("@%d x%x x%x",i,cpu_serial()[i],data[i+1]);
        return 0;
#endif
    }

    // OK, it's for us. Now check extension
    u_int8_t flag = 0;
    u_int8_t timer = 0;

    if(*data & 0x10) {
        if(len < cpu_serial_len+2)
            return 0;
        data += cpu_serial_len+1;
        flag = *data++;
        if (flag & 0x80) {
            if(len < cpu_serial_len+3)
                return 0;
            timer = *data++;
        }
    }

    if (msg->src == -4) {
        if (my_addr > 0 && msg->dst == -4) {
            logger_addr("Address lookup collision??");
            send_serial(-1, 0, 0x10,0);
        }
        logger_addr("NoLookup1 %d",msg->dst);
        return 0;
    }
    if (msg->src >= 0) {
        if (msg->dst == -4) {
            // neg reply? by a client
            logger_addr("Addr NACK by %d: x%x",msg->src,flag);
            if(flag & 0x10) {
                // TODO invent a random address?
            } else {
                // ???
            }
            return 1;
        }
        logger_addr("NoLookup2 %d",msg->src);
        return 0;
    }
    if (msg->dst > 0) {
        // Got our address
        if(my_addr == 0xFF) {
            my_addr = msg->dst;
            if(timer) {
                addr_state = AS_GET_DELAY;
                mf_set(&addr_poll.mf, timer);
            } else {
                addr_state = AS_GET_OK;
                mf_stop(&addr_poll.mf);
                setup_addr_done();
            }
            return TRUE;
        } else if(my_addr != msg->dst) {
            logger("Addr change! %d > %d",my_addr,msg->dst);
            my_addr = msg->dst;
            // TODO stack reset, temporary takedown, timer
        }
        return 1;
    }
    if (msg->dst != -4) {
        logger_addr("NoLookup2 %d",msg->dst);
        return 0;
    }

    // negative. TODO eval flags
    if (addr_state < AS_GET_END)
        addr_state = (enum _AS)((u_int8_t)addr_state+1);
    if (!timer)
        timer = mf_random(addr_state*30*MINI_F, addr_state*120*MINI_F);
    mf_set(&addr_poll.mf, timer);
    return 1;
}

struct poll_reply {
    struct mtick mt;
    int8_t dst;
    u_int8_t code;
};

static bool poll_reply_proc(MTICK _mt)
{
    poll_reply *pr = container_of(_mt, struct poll_reply, mt);
    send_serial(pr->dst,pr->code,0,0);
    delete pr;
    return FALSE;
}

static bool process_control_poll(BusMessage msg, u_int8_t *data, msglen_t len)
{
    if(len < 1)
        return FALSE;
    if(msg->dst != -4 && msg->dst != my_addr)
        return FALSE;

    if (addr_state == AS_GET_END) {
        // timed out requesting an address: restart
        addr_state = AS_GET_START;
        mf_set(&addr_poll.mf, *data);
        return TRUE;
    }
    if (addr_state >= AS_GET_START) {
        // already requesting an address
        return TRUE;
    }

    if(my_addr != 0xFF) {
        // already have an address
        logger("Addr Err s=%d adr=%d", addr_state, my_addr);
        return FALSE;  // should not happen
    }
    
    struct poll_reply *mx = new poll_reply;
    mtick_init(&mx->mt, poll_reply_proc);
    mf_set_randfract(&mx->mt.mf, data[1], 0);
    mx->dst = msg->src;
    mx->code = *data & 0x1F;
    return TRUE;
}

static char process_control(BusMessage msg)
{
    msglen_t len = msg_length(msg);
    if (len < 1) 
        return 0;
    u_int8_t *data = msg_start(msg);
    switch(*data >> 5) {
    case 0:
        return process_control_addr_assign(msg, data,len);
    case 1:
        return process_control_poll(msg, data,len);
    default:
        return 0;
    }
}

IN_C char process_msg_in(BusMessage msg)
{
    char res = 0;
    switch(msg->code == 0) {
    case 0:
        res = process_control(msg);
        break;
    default:
        /* TODO */
        break;
    }
    msg_free(msg);
    return res;
}


