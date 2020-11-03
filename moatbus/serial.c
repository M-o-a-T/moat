
/*
Serial handler for MoatBus
*/

#include <sys/types.h>
#include <stddef.h>
#include <stdlib.h>
#include <assert.h>

#include "moatbus/type.h"
#include "moatbus/serial.h"
#include "moatbus/crc.h"


static void sb_clear_in(SerBus sb)
{
    sb->crc_in = 0;
    sb->s_in = S_IDLE;
    msg_start_add(sb->m_in);
}

static void sb_alloc_in(SerBus sb)
{
    BusMessage msg = msg_alloc(20);
    if (sb->m_in_first != NULL)
        sb->m_in->next = msg;
    else
        sb->m_in_first = msg;
    sb->m_in = msg;
    sb_clear_in(sb);
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
    while (sb->m_in_first) {
        BusMessage msg = sb->m_in_first;
        sb->m_in_first = msg->next;
        msg_free(msg);
    }
    while (sb->m_out) {
        BusMessage msg = sb->m_out;
        sb->m_out = msg->next;
        msg_free(msg);
    }
    free(sb);
}

// start sending this frame
void sb_send(SerBus sb, BusMessage msg)
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
        if (sb->crc_in)
            sb->err_crc++;
        else
            sb_alloc_in(sb);
        sb_clear_in(sb);
        break;

    case S_DONE: // should not happen
    case S_ACK: // should not happen
        break;
    }
}

// Send char?
int16_t sb_byte_out(SerBus sb)
{
    u_int8_t c;
    u_int16_t len;
    switch(sb->s_out) {
    case S_IDLE:
        assert(sb->m_out == NULL);
        return -1;
    case S_ACK:
        assert (sb->ack_out);
        if(!--sb->ack_out)
            sb->s_out = sb->m_out ? S_INIT : S_IDLE;
        return 0x06;
    case S_INIT:
        assert (sb->m_out != NULL);
        msg_start_extract(sb->m_out);
        sb->s_out = S_LEN;
        sb->crc_out = 0;
        return (sb->m_out->prio & 0x03) +1;
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

        BusMessage msg = sb->m_out;
        sb->m_out = msg->next;
        msg_free(msg);
        if (sb->ack_out)
            sb->s_out = S_ACK;
        else if (sb->m_out == NULL)
            sb->s_out = S_IDLE;
        else
            sb->s_out = S_INIT;
        return c;

    case S_DONE:  // should not happen
        break;
    }
    return 0x00;  // should not happen
}

// Received message?
BusMessage sb_recv(SerBus sb)
{
    if (sb->m_in == sb->m_in_first)
        return NULL;

    BusMessage msg = sb->m_in_first;
    sb->m_in_first = msg->next;
    sb->ack_out ++;
    if (sb->s_out == S_IDLE)
        sb->s_out = S_ACK;
    
    msg_read_header(msg);
    return msg;
}

u_int8_t sb_recv_ack(SerBus sb)
{
    u_int8_t c = sb->ack_in;
    sb->ack_in = 0;
    return c;
}

bool sb_idle(SerBus sb) {
    if (sb->s_in != S_IDLE) {
        if(++sb->idle > 3) {
            sb->idle = 0;
            sb->err_lost++;
            sb->s_in = S_IDLE;
            sb->crc_in = 0;
            msg_start_add(sb->m_in);
        }
        return true;
    } else {
        sb->idle = 0;
        return false;
    }
}

