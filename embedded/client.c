#include "embedded/client.h"
#include "embedded/timer.h"
#include "embedded/main.h"
#include "embedded/logger.h"
#include "moatbus/util.h"
#include <memory.h>

static struct mtick adr_poll NO_INIT;
u_int8_t my_addr;

enum _AS {
    AS_GET_OK = 0,
    AS_GET_START = 1,
    AS_GET_LAST = 5,
    AS_GET_DELAY = 6,
} adr_state NO_INIT;

#ifdef DEBUG_ADR
#define logger_adr logger
#else
#define logger_adr(s, ...) do {} while(0)
#endif

void get_addr()
{
    if(adr_state == AS_GET_OK)
        return;
    if(adr_state == AS_GET_START) {
        // more random delay
        adr_state += 1;
#ifndef DEBUG_ADR
        u_int8_t mf;
        mf_set(&adr_poll.mf, mf = mf_random(1*MINI_F, 5*MINI_F));
        logger("ADR jn %d",mf);
        return;
#endif
    }
    if (adr_state <= AS_GET_LAST) {
        BusMessage m = msg_alloc(cpu_serial_len+3);
        m->src = -4;
        m->dst = -4;
        m->code = 0;
        m->prio = MOAT_WIRES-1;
        msg_add_char(m, cpu_serial_len-1);
        msg_add_data(m, cpu_serial(),cpu_serial_len);
        // no flag byte 
        send_msg(m);

        // schedule retry
#ifdef DEBUG_ADR
        mf_set(&adr_poll.mf, 36); // 10 seconds
#else
        mf_set(&adr_poll.mf, mf_random(adr_state*30*MINI_F, adr_state*120*MINI_F));
#endif
        if (adr_state < AS_GET_LAST)
            adr_state += 1;
        return;
    }
    if (adr_state == AS_GET_DELAY) {
        adr_state = AS_GET_OK;
        setup_addr_done();
        return;
    }
}

IN_C void setup_addr()
{
    my_addr = ~0;
}

IN_C void setup_get_addr()
{
    adr_state = AS_GET_START;
    mtick_init(&adr_poll, get_addr);
#ifdef DEBUG_ADR
    mf_set(&adr_poll.mf, MINI_F); // 1 sec
#else
    u_int8_t mf;
    mf_set(&adr_poll.mf, (mf = mf_random(2*MINI_F, 15*MINI_F)));
    logger("ADR in %d",mf);
#endif
}

static char process_control_addr_assign(BusMessage msg, u_int8_t *data, msglen_t len)
{
    if (len < cpu_serial_len+1) {
        logger_adr("short1 %d",len);
        return 0;
    }
    if((*data & 0x0F) != cpu_serial_len-1) {
        logger_adr("len %d %d",*data & 0x0F, cpu_serial_len-1);
        return 0;
    }

    if(memcmp(data+1,cpu_serial,cpu_serial_len)) {
        logger_adr("wrong serial");
        return 0;
    }

    // OK, it's for us. Now check extension
    u_int8_t flag;
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
    } else {
        flag = 0;
    }

    if (msg->src == -4) {
        if (msg->dst == -4) {
            logger_adr("Address lookup collision??");
            BusMessage m = msg_copy(msg);
            m->src = my_addr;
            m->dst = -4;
            data = msg_start(m);
            *data |= 0x80;
            data += cpu_serial_len+1;
            *data = 0x10; // known
            return 1;
        }
        logger_adr("NoLookup1 %d",msg->dst);
        return 0;
    }
    if (msg->src >= 0) {
        if (msg->dst == -4) {
            // neg reply? by a client
            logger_adr("Addr NACK by %d: x%x",msg->src,flag);
            if(flag & 0x10) {
                // TODO invent a random address?
            } else {
                // ???
            }
            return 1;
        }
        logger_adr("NoLookup2 %d",msg->src);
        return 0;
    }
    if (msg->dst > 0) {
        // Got our address
        if(my_addr == 0xFF) {
            my_addr = msg->dst;
            if(timer) {
                adr_state = AS_GET_DELAY;
                mf_set(&adr_poll.mf, timer);
            } else {
                adr_state = AS_GET_OK;
                setup_addr_done();
            }
            return true;
        } else if(my_addr != msg->dst) {
            logger("Adr change! %d > %d",my_addr,msg->dst);
            my_addr = msg->dst;
            // TODO stack reset, temporary takedown, timer
        }
        return 1;
    }
    if (msg->dst != -4) {
        logger_adr("NoLookup2 %d",msg->dst);
        return 0;
    }

    // negative. TODO eval flags
    if (adr_state < AS_GET_LAST)
        adr_state++;
    if (!timer)
        timer = mf_random(adr_state*30*MINI_F, adr_state*120*MINI_F);
    mf_set(&adr_poll.mf, timer);
    return 1;
}

static char process_control(BusMessage msg)
{
    msglen_t len = msg_length(msg);
    if (len < 1) 
        return 0;
    u_int8_t *data = msg_start(msg);
    if (!(*data >> 5))
        return process_control_addr_assign(msg, data,len);
    return 0;
}

IN_C char process_msg_in(BusMessage msg)
{
    if (msg->code == 0)
        return process_control(msg);
    return 0;
}


