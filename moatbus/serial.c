
/*
Serial handler for MoatBus
*/

#include <sys/types.h>
#include <stddef.h>
#include <stdlib.h>
#include <assert.h>

#include "moatbus/serial.h"
#include "moatbus/crc.h"


static void sb_alloc_in(SerBus sb)
{
    sb->m_in = msg_alloc(20);
    sb->crc_in = 0;
    sb->s_in = S_IDLE;
    msg_start_add(sb->m_in);
}

// Queue+send a message
SerBus sb_alloc(void)
{
    SerBus sb = calloc(sizeof(*sb),1);
    sb_alloc_in(sb);
    return sb;
}

void sb_free(SerBus sb)
{
    if (sb->m_in)
        msg_free(sb->m_in);
    free(sb);
}

// start sending this frame
void sb_send(SerBus sb, BusMessage msg, u_int8_t prio)
{
    if (sb->m_out != NULL)
        sb->m_out_last->next = msg;
    else
        sb->m_out = msg;
    sb->m_out_last = msg;
    msg->next = NULL;

    if (sb->s_out == S_IDLE)
        sb->s_out = S_INIT;
}

void sb_send_ack(SerBus sb)
{
    sb->ack_out ++;
}

// process an incoming serial character
void sb_byte_in(SerBus sb, u_int8_t c)
{
    sb->idle = 0;
    switch(sb->s_in) {
    case S_IDLE:
        if (c == 0x06)
            sb->ack_in++;
        else if (c > 0 && c <= 0x04)
            sb->s_in = S_LEN;
        else
            sb->err_spurious++;
        break;
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
        msg_add_chunk(sb->m_in,c,8);
        sb->crc_in = crc16_update(sb->crc_in,c);
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
            sb->err_crc++;
            sb->s_in = S_IDLE;
            sb->crc_in = 0;
            msg_start_add(sb->m_in);
        }
        else
            sb->s_in = S_DONE;
        break;
    case S_DONE:
        // ugh, overflow
        sb->err_overflow++;
        break;
    }
}

// Send char?
int16_t sb_byte_out(SerBus sb)
{
    static u_int8_t prio[] = "\x01\x02\x03\x04";
    u_int8_t c;
    u_int16_t len;
    switch(sb->s_out) {
    case S_IDLE:
        assert(sb->m_out == NULL);
        if (sb->ack_out) {
            --sb->ack_out;
            return 0x06;
        }
        return -1;
    case S_INIT:
        assert (sb->m_out != NULL);
        if (sb->ack_out) {
            --sb->ack_out;
            return 0x06;
        }
        msg_start_extract(sb->m_out);
        sb->s_out = S_LEN;
        sb->crc_out = 0;
        return *prio; // TODO add actual prio
    case S_LEN:
        len = msg_bits(sb->m_out) >> 3;
        if (len >= 0x80) {
            sb->s_out = S_LEN2;
            return 0x80 | (len>>7);
        } else {
            sb->s_out = S_DATA;
            return len;
        }
    case S_LEN2:
        len = msg_bits(sb->m_out) >> 3;
        sb->s_out = S_DATA;
        return len & 0xFF;
    case S_DATA:
        c = msg_extract_chunk(sb->m_out,8);
        sb->crc_out = crc16_update(sb->crc_out, c);
        if (!msg_extract_more(sb->m_out))
            sb->s_out = S_CRC1;
        return c;
    case S_CRC1:
        sb->s_out = S_CRC2;
        return sb->crc_out >> 8;
    case S_CRC2:
        c = sb->crc_out & 0xFF;
        sb->m_out = sb->m_out->next;
        if (sb->m_out == NULL)
            sb->s_out = S_IDLE;
        else
            sb->s_out = S_INIT;
        return c;
    }
}

// Received message?
BusMessage sb_recv(SerBus sb, u_int8_t *prio)
{
    if (sb->s_in != S_DONE)
        return NULL;

    BusMessage msg = sb->m_in;
    sb_alloc_in(sb);
    
    msg_read_header(msg);
    return msg;
}

u_int8_t sb_recv_ack(SerBus sb)
{
    u_int8_t c = sb->ack_in;
    sb->ack_in = 0;
    return c;
}

char sb_idle(SerBus sb) {
    if (sb->s_in != S_IDLE) {
        if(++sb->idle > 3) {
            sb->idle = 0;
            sb->err_lost++;
            sb->s_in = S_IDLE;
            sb->crc_in = 0;
            msg_start_add(sb->m_in);
        }
        return 1;
    } else {
        sb->idle = 0;
        return 0;
    }
}

