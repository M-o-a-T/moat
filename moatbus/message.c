/*
Message structure for MoatBus
*/

#define _GNU_SOURCE
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>

#include "message.h"

BusMessage msg_alloc(u_int16_t maxlen)
{
    BusMessage msg;
    maxlen += 8; // header, additional frame, whatever
    u_int8_t *data = malloc(maxlen);
    memset(data,0,maxlen);

    msg = calloc(sizeof (*msg), 1);
    msg->data = data;
    *msg->data = 1;
    msg->data_max = maxlen;
    msg->data_off = msg->data_end = MSG_MAXHDR;
    msg->result = RES_FREE;

    return msg;
}

BusMessage msg_copy(BusMessage orig)
{
    BusMessage msg = malloc(sizeof(BusMessage *));
    memcpy(msg, orig, sizeof(BusMessage *));
    msg->next = NULL;
    *msg->data += 1;
    return msg;
}

void msg_init(BusMessage msg, u_int8_t *data, u_int16_t len)
{
    memset(msg,0,sizeof(*msg));
    msg->data = data-MSG_MAXHDR;
    *msg->data = 0x80;
    msg->data_off = MSG_MAXHDR;
    msg->data_end = msg->data_off+len;
    msg->result = RES_FREE;
}

void msg_free(BusMessage msg)
{
    if(msg->data_max) {
        if (!--*msg->data)
            free(msg->data);
    }
    free(msg);
}

void msg_resize(BusMessage msg, u_int16_t maxlen)
{
    u_int8_t *data;
    if(msg->data_max == 0)
        return; // TODO assertion error?
    if(msg->data_max >= maxlen)
        return;
    data = realloc(msg->data, maxlen);
    if (data) {
        memset(data+msg->data_max, 0,maxlen-msg->data_max);
        msg->data = data;
        msg->data_max = maxlen;
    } else {
        free(msg->data);
        msg->data = NULL;
        msg->data_max = 0;
    }
}

static char *msg_info_buf = NULL;
const char* msg_info(BusMessage msg)
{
    if(msg_info_buf)
        free(msg_info_buf);
    u_int16_t ml = msg_length(msg);
    asprintf(&msg_info_buf, "Msg< src:%d dst:%d cmd:x%x %d:%*s >", msg->src,msg->dst,msg->code,
            ml,ml,msg_start(msg));
    return msg_info_buf;
}

// Start address of the message (data onlyy)
u_int8_t *msg_start(BusMessage msg)
{
    return msg->data+msg->data_off;
}

// Length of the message, excluding header and incomplete bits
u_int16_t msg_length(BusMessage msg)
{
    return msg->data_end-msg->data_off;
}

// Length of the complete message (bits)
u_int16_t msg_bits(BusMessage msg)
{
    return (msg->data_end-msg->data_off+msg->hdr_len)*8 + (8-msg->data_end_off);
}

// Length of already-processed/transmitted message (bits)
u_int16_t msg_sent_bits(BusMessage msg)
{
    return (msg->data_pos-msg->data_off+msg->hdr_len)*8 + (8-msg->data_pos_off);
}


// Copy header data from the message to data fields
void msg_read_header(BusMessage msg)
{
    if (msg->hdr_len > 0) // already done
        return;

    // analyze the current buffer
    u_int8_t *buf = msg->data+msg->data_off;
    u_int8_t *ebuf = msg->data+msg->data_end;
    if (buf >= ebuf)
        return;
    if (*buf & 0x80) {
        // 1 D D *
        msg->dst = (*buf >> 5) | 0xFC;
        if (*buf & 0x10) {
            // 1 D D 1 S S C C
            msg->src = (*buf >> 2) | 0xFC;
            msg->code = *buf++ & 0x03;
        } else {
            // 1 D D 0 S S S S | S S S C C C C C
            if (buf+1 > ebuf) {
                msg->dst = 0;
                return;
            }
            msg->src = *buf++ << 3;
            msg->src |= *buf >> 5;
            msg->code = *buf++ & 0x1F;
        }
    } else {
        // 0 D D D D D D D | *
        if (buf+1 >= ebuf)
            return;
        msg->dst = *buf++;
        if (*buf & 0x80) {
            // 0 D D D D D D D | 1 S S C C C C C
            msg->src = (*buf >> 5) | 0xFC;
            msg->code = *buf++ & 0x1F;
        } else {
            if (buf+2 > ebuf) {
                msg->dst = 0;
                return;
            }
            // 0 D D D D D D D | 0 S S S S S S S | CC
            msg->src = *buf++;
            msg->code = *buf++;
        }
    }
    msg->hdr_len = buf-(msg->data+msg->data_off);
    msg->data_off = buf-msg->data;
}

// Add header bytes to the message
void msg_add_header(BusMessage msg)
{
    u_int8_t *buf = msg->data+msg->data_off;

    if(msg->dst < 0) {
        if(msg->src < 0) {
            // 1 D D 1 S S C C
            *--buf = 0x80 | ((msg->dst&0x03)<<5) | 0x10 | ((msg->src&0x03)<<2) | (msg->code&0x03);
        } else {
            // 1 D D 0 S S S S | S S S C C C C C
            u_int8_t m = msg->src;
            *--buf = (m<<5) | (msg->code&0x1F);
            *--buf = 0x80 | ((msg->dst&0x03)<<5) | (m>>3);
        }
    } else {
        if(msg->src < 0) {
            // 0 D D D D D D D | 1 S S C C C C C
            *--buf = 0x80 | ((msg->src&0x03)<<5) | (msg->code&0x1F);
            *--buf = msg->dst;
        } else {
            // 0 D D D D D D D | 0 S S S S S S S | CC
            *--buf = msg->code;
            *--buf = msg->src;
            *--buf = msg->dst;
        }
    }
    msg->hdr_len = msg->data+msg->data_off-buf;
}

BusMessage msg_copy_bits(BusMessage msg, u_int8_t off)
{
    BusMessage nm;
    u_int8_t off_bits = off&7;
    off >>= 3;

    nm = msg_alloc(off < (MSG_MINBUF*2/3) ? MSG_MINBUF : off*2);
    if (!off_bits) {
        if (off)
            memcpy(nm->data, msg->data, off+msg->data_off);
    } else {
        if (off)
            memcpy(nm->data, msg->data, off-1);
        nm->data[off] = msg->data[off] & ~((1<<(8-off))-1);
    }
    nm->data_off = msg->data_off;
    nm->data_end = nm->data_off+off;
    return nm;
}


// prepare a buffer for sending    
void msg_start_extract(BusMessage msg)
{
    msg_add_header(msg);
    msg->data_pos = msg->data_off-msg->hdr_len;
    msg->data_pos_off = 8;
}

// are there more data to extract?
bool msg_extract_more(BusMessage msg)
{
    if (msg->data_pos < msg->data_end)
        return true;
    if (msg->data_pos_off > msg->data_end_off)
        return true;
    return false;
}

u_int16_t msg_extract_chunk(BusMessage msg, u_int8_t frame_bits)
{
    u_int16_t data = 0;
    u_int8_t fb;

    u_int8_t *buf = msg->data+msg->data_pos;
    u_int8_t bits = msg->data_pos_off;

    u_int16_t x_bits = ((msg->data_end<<3) - msg->data_end_off) - ((msg->data_pos<<3) - msg->data_pos_off);
    // should be 8-data_*_off in each term, but the 8 cancels out

    assert(frame_bits <= 16);
    assert(x_bits>0);
    if (frame_bits > x_bits) {
        fb = x_bits;
        x_bits = frame_bits-x_bits;
    } else {
        x_bits = 0;
        fb = frame_bits;
    }
    while(fb) {
        if(bits == 8) {
            if (fb < 8) {
                bits -= fb;
                data |= *buf >> bits;
                break;
            } else {
                fb -= 8;
                data |= *buf++ << fb;
            }
        } else if(bits >= fb) {
            u_int8_t m = ((1<<bits)-1);
            bits -= fb;
            data |= (*buf & m) >> bits;
            if (!bits) {
                buf += 1;
                bits = 8;
            }
            break;
        } else {
            fb -= bits;
            data |= (*buf++ & ((1<<bits)-1)) << fb;
            bits = 8;
        }
    }
    if (x_bits) {
        assert(frame_bits<16);
        if (x_bits >= 8) {
            // assume frame_bits=11, buffer contains only 2 bits:
            // before this: data = AB0-00000000
            // We want to return: 1000-00000AB0
            data = (data<<(x_bits-8)) | (1<<(frame_bits));
        } else {
            data <<= x_bits;
        }
    }
    msg->data_pos = buf - msg->data;
    msg->data_pos_off = bits;

    return data;
}

u_int16_t msg_drop(BusMessage msg, u_int8_t bits)
{
    u_int16_t res = 0;
    u_int8_t shift = 0;
    if(msg->data_end_off < 8) {
        if (bits < 8-msg->data_end_off) {
            res = (msg->data[msg->data_end] >> msg->data_end_off) & ((1<<bits)-1);
            msg->data_end_off += bits;
            return res;
        }
        res = msg->data[msg->data_end] >> msg->data_end_off;
        shift = 8-msg->data_end_off;
        bits -= shift;
        msg->data_end_off = 8;
    }
    while (bits >= 8) {
        res |= msg->data[--msg->data_end] << shift;
        shift += 8;
        bits -=8;
    }
    if (bits) {
        res |= (msg->data[--msg->data_end] & ((1<<bits)-1)) << shift;
        msg->data_end_off = bits;
    }
    return res;
}

void msg_align(BusMessage msg)
{
    msg->data_end_off = 8;
}


// prepare a buffer for receiving
void msg_start_add(BusMessage msg)
{
    msg->data_off = MSG_MAXHDR-1;
    msg->hdr_len = 0;
    msg->data_end = msg->data_off;
    msg->data_end_off = 8;
}

void msg_add_chunk(BusMessage msg, u_int16_t data, u_int8_t frame_bits)
{
    msg_resize(msg, msg->data_end+3);

    u_int8_t *buf = msg->data+msg->data_end;
    u_int8_t bits = msg->data_end_off;

    assert(frame_bits <= 16);
    while(frame_bits) {
        if(bits == 8) {
            if (frame_bits < 8) {
                bits -= frame_bits;
                *buf = data << bits;
                break;
            } else {
                frame_bits -= 8;
                *buf++ = data >> frame_bits;
            }
        } else if(bits > frame_bits) {
            u_int8_t m = ((1<<bits)-1);
            bits -= frame_bits;
            *buf |= (data << bits) & m;
            break;
        } else {
            frame_bits -= bits;
            *buf++ |= ((data>>frame_bits) & ((1<<bits)-1));
            bits = 8;
        }
    }
    msg->data_end = buf - msg->data;
    msg->data_end_off = bits;
}

void msg_add_in(BusMessage msg, BusMessage orig, u_int16_t bits)
{
    if(!bits)
        return;
    u_int8_t bb = bits & 7;
    bits >>= 3;
    msg_resize(msg, bits+3);
    memcpy(msg->data+msg->data_off, orig->data+orig->data_off, bits+(bb != 0));

    msg->data_end = msg->data_off + bits;
    msg->data_end_off = 8-bb;
}

// prepare a buffer to add content to be transmitted
void msg_start_send(BusMessage msg)
{
    msg->hdr_len = 0;
    msg->data_end = msg->data_off;
    msg->data_end_off = 8;
}

void msg_add_data(BusMessage msg, const u_int8_t *data, u_int16_t len) // bytes
{
    if (msg->data_end_off != 8) {
        msg->data_end += 1;
        msg->data_end_off = 8;
    }
    memcpy(msg->data+msg->data_end, data, len);
    msg->data_end += len;
    msg->data_end_off = 8;
}


// /// //// deprecated part //// /// //

#include "crc.h"

void msg_fill_crc(BusMessage msg, u_int8_t frame_bits, u_int16_t crc, u_int8_t crc_bits)
{
    msg_add_header(msg);

    u_int16_t m_bits = msg_bits(msg);
    u_int16_t bits = m_bits+1+crc_bits;
    bits = ((bits-1)/frame_bits+1)*frame_bits; // round up to frame_bits
    bits -= m_bits+1+crc_bits;
    
    if(bits)
        msg_add_chunk(msg, 0, bits);
    msg_add_chunk(msg, (bits>7), 1);
    msg_add_chunk(msg, crc, crc_bits);
}

