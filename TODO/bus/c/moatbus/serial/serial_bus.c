
/*
Serial handler for MoatBus
*/

#include <sys/types.h>
#include <stddef.h>
#include <stdlib.h>
#include <assert.h>

#include "moat/common.h"
#include "moat/serial_bus.h"
#include "moat/crc.h"

#define ERRF_(x) S_ERR_##x
#define ERR(sb,f) do { \
        (sb)->errors += 1; \
        (sb)->errflag |= ERRF_(f); \
    } while(0)

static void sb_clear_in(SerBus sb)
{
    sb->crc_in = 0;
    sb->s_in = S_IDLE;
    if(sb->m_in)
        msg_start_add(sb->m_in);
}

static void sb_alloc_in(SerBus sb)
{
    if(sb->m_in == NULL) {
        sb->m_in = msg_alloc(20);
    }
    sb_clear_in(sb);
}

static void sb_idle(void *arg) {
    SerBus sb = arg;
    if (sb->s_in == S_ALLOC) {
        sb_alloc_in(sb);
        if(sb->s_in == S_ALLOC) { // out-of-memory persists
            return FALSE;
        }
        cond_signal(&sb->recv_wait);
    } else if (sb->s_in != S_IDLE) {
        ztimer_remove(ZTIMER_MSEC,&sb->recv_timeout);
        ERR(sb,TIMER);
        sb_clear_in(sb);
    } else {
        return FALSE;
    }
}

void sb_init(SerBus sb, uart_t serial, )
{
    memset(sb,0,sizeof(*sb));

    mutex_init(&sb->send_lock);
    mutex_init(&sb->recv_lock);
    cond_init(&sb->recv_wait);

    sb->recv_timeout.callback = sb_idle;
    sb->recv_timeout.arg = sb;

#if MOAT_SER_INBUF_SIZE
    tsrb_init(&sb->inbuf, sb->inbuf_data, MOAT_SER_INBUF_SIZE);
#endif
    sb_alloc_in(sb);
}

void sb_deinit(SerBus sb)
{
    ztimer_remove(ZTIMER_MSEC,&sb->recv_timeout);

    if (sb->m_in) {
        msg_free(sb->m_in);
        sb->m_in = NULL;
    }
    if(sb->m_in_proc) {
        msg_free(sb->m_in_proc);
        sb->m_in_proc = NULL;
    }
    cond_broadcast(&sb->recv_wait);
}



// process an incoming serial character
void sb_byte_in(SerBus sb, u_int8_t c)
{
    switch(sb->s_in) {
    case S_IDLE:
        if (c == 0x06) {
            sb->ack_in++;
            break;
        } else if (c == 0x01 || c == 0x02 || c == 0x81 || c == 0x82) {
            sb->s_in = S_LEN;
            c -= 1;
            sb->prio = (c>>6) | (c&1);
            break;
        } else if (!(0xC0 & ~c)) {
            // UTF-8 lead-in character found. Skip 0x10xxxxxx bytes so
            // they're not misrecognized as high-prio frame starts.
            sb->s_in = S_UTF8;
            c ^= 0xff;
            int n = 0;
            while(c) {
                n += 1;
                c >>= 1;
            }
            sb->len_in = 6-n;
            ztimer_set(ZTIMER_MSEC,&sb->recv_timeout,30);
        }
        goto buff;
    case S_UTF8:
        if (((c & 0xC0) != 0x80) || !--sb->len_in) {
            sb->s_in = S_IDLE;
        }
        goto buff;

    case S_INIT:
        sb->s_in = S_LEN;
        break;
    case S_LEN:
        if (c & 0x80) {
            sb->len_in = (c & 0x7F) << 8;
            sb->s_in = S_LEN2;
        } else {
            sb->len_in = c;
            sb->s_in = S_DATA;
        }
        break;
    case S_LEN2:
        sb->len_in |= c;
        sb->s_in = S_DATA;
        break;
    case S_DATA:
        if(sb->m_in && !msg_add_chunk(sb->m_in,c,8)) {
            msg_free(sb->m_in);
            sb->m_in = NULL;
            // error flag is set later
        }
        sb->crc_in = mcrc16_update(sb->crc_in,c);
        if(!--sb->len_in)
            sb->s_in = S_CRC1;
        break;
    case S_CRC1:
        sb->crc_in ^= c<<8;
        sb->s_in = S_CRC2;
        break;
    case S_CRC2:
        sb->crc_in ^= c;
        if (sb->crc_in) {
            ERR(sb,CRC);
        } else if(!sb->m_in) {
            ERR(sb,MEM);
        } else if(sb->m_in_proc != NULL) {
            ERR(sb,OVERRUN);
        } else {
            sb->m_in_proc = sb->m_in;
            sb->m_in = NULL;
            cond_signal(&sb->recv_wait);
        }
        ztimer_remove(ZTIMER_MSEC,&sb->recv_timeout);
        sb_alloc_in(sb);
        break;

    case S_DONE: // should not happen
    case S_ACK: // should not happen
        break;
    }
    return;

buff:
#if MOAT_SER_INBUF_SIZE
    if(tsrb_add_one(&sb->inbuf, c) < 0) {
        tsrb_clear(&sb->inbuf);
        sb->err_overflow++;
    } else
        cond_signal(&sb->recv_wait);
#else
    sb->err_overflow++;
#endif
    return;
}

#if MOAT_SER_INBUF_SIZE
int16_t sb_getchar(SerBus sb, bool block)
{
    uint8_t c;
    mutex_lock(&sb->recv_lock);
    while(block && tsrb_empty(&sb->inbuf)) {
        cond_wait(&sb->recv_wait);
    }
    c = tsrb_get_one(&sb->inbuf);
    // conveniently returns -1 if empty
    mutex_unlock(&sb->recv_lock);

    return c;
}
#endif

void _sb_putchar(SerBus sb, uint8_t c)
{
    uart_write(sb->serial, &c,1);
}

void sb_putchar(SerBus sb, uint8_t c)
{
    mutex_lock(&sb->send_lock);
    _sb_putchar(sb,c);
    mutex_unlock(&sb->send_lock);
}

// Send a message.
//
// The message is consumed.
//
void sb_send(SerBus sb, BusMessage msg)
{
    u_int8_t c;
    u_int16_t len;
    u_int16_t crc_out;

    msg_start_extract(msg);
    mutex_lock(&sb->send_lock);
    crc_out = 0;

    c = (msg->prio & 1 + 1) | (sg->prio & 2) << 6;
    _sb_putchar (c);

    len = msg_bits(msg) >> 3;
    if (len >= 0x80) {
        _sb_putchar(0x80 | (len>>7));
        _sb_putchar(len & 0xFF);
    } else {
        sb->s_out = S_DATA;
        _sb_putchar(len);
    }
    while(msg_extract_more(msg)) {
        c = msg_extract_chunk(msg,8);
        sb->crc_out = mcrc16_update(sb->crc_out, c);
        _sb_putchar(c);
    }
    _sb_putchar(sb->crc_out >> 8);
    _sb_putchar(sb->crc_out & 0xFF);

    msg_free(msg);
    mutex_unlock(&sb->send_lock);
}

// Received message?
BusMessage sb_recv(SerBus sb, bool blocking)
{
    mutex_lock(&sb->recv_lock);
    if (sb->m_in_proc == NULL) {
        if(!blocking) {
            mutex_unlock(&sb->recv_lock);
            return NULL;
        }
        cond_wait(&sb->recv_wait, &sb->recv_lock);
    }

    BusMessage msg = sb->m_in_proc;
    sb->m_in_proc = NULL;
    mutex_unlock(&sb->recv_lock);

    if(msg) {
        sb_putchar(0x06); // ACK
        msg_read_header(msg);
    }
    return msg;
}

u_int8_t sb_recv_ack(SerBus sb)
{
    u_int8_t c = sb->ack_in;
    sb->ack_in = 0;
    return c;
}

