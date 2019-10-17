/*
Message structure for MoatBus
*/

#include <stdlib.h>
#include <string.h>
#include <assert.h>

#include "message.h"
#include "crc.h"

BusMessage msg_alloc(u_int16_t maxlen)
{
    BusMessage msg;
    maxlen += 7; // header, CRC, one additional frame
    u_int8_t *data = calloc(maxlen, 1);
    msg = calloc(sizeof (*msg), 1);
    msg->data = data;
    msg->data_max = maxlen;
    msg->data_off = msg->data_end = MSG_MAXHDR;

    return msg;
}

void msg_free(BusMessage msg)
{
    free(msg->data);
    free(msg);
}

void msg_resize(BusMessage msg, u_int16_t maxlen)
{
    u_int8_t *data;
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

// Start address of the message (data onlyy)
u_int8_t *msg_start(BusMessage msg)
{
    return msg->data+msg->data_off;
}

// Length of the message, excluding header and CRC
u_int16_t msg_length(BusMessage msg)
{
    if (!msg_check_crc(msg))
        return 0;
    return msg->data_end-msg->data_off;
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
            if (buf+1 >= ebuf) {
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
            if (buf+2 >= ebuf) {
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
            *--buf = 0x80 | (msg->dst<<5) | 0x10 | ((msg->src&0x03)<<2) | (msg->code&0x03);
        } else {
            // 1 D D 0 S S S S | S S S C C C C C
            u_int8_t m = msg->src;
            *--buf = (m<<5) | (msg->code&0x1F);
            *--buf = 0x80 | ((msg->dst&0x03)<<5) | (m>>3);
        }
    } else {
        if(msg->src < 0) {
            // 0 D D D D D D D | 1 S S C C C C C
            *--buf = 0x80 | (msg->src<<5) | (msg->code&0x1F);
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

void msg_add_crc(BusMessage msg)
{
    if (msg->has_crc)
        return;

    if (msg->data_end > msg->data_max-3)
        msg_resize(msg, msg->data_end+3);
    if (msg->data_end_off < 8) {
        msg->data_end += 1;
        msg->data_end_off = 8;
    }

    msg_add_header(msg);
        
    u_int16_t off = msg->data_off-msg->hdr_len;
    u_int8_t *buf = msg->data+off;
    u_int16_t len = msg->data_end-off;

    if (msg->data_end-msg->data_off <= MSG_MAXCRC8) {
        u_int8_t crc;
        crc = crc8(buf, len);
        msg->data[msg->data_end++] = crc;
    } else {
        u_int16_t crc;
        crc = crc16(buf, len);
        msg->data[msg->data_end++] = crc>>8;
        msg->data[msg->data_end++] = crc&0xFF;
    }
    msg->has_crc = 1;
}

char msg_check_crc(BusMessage msg)
{
    if (!msg->has_crc)
        return 1;
    msg_read_header(msg);

    u_int16_t off = msg->data_off-msg->hdr_len;
    u_int8_t *buf = msg->data+off;
    u_int16_t len = msg->data_end-off;
    
    if (msg->data_end-msg->data_off-2 <= MSG_MAXCRC8) {
        u_int8_t crc;
        crc = crc8(buf, len-1);
        if (crc == 0 && (buf[len-1] == 0xFF)) {
            msg->data_end -= 2;
        } else {
            crc = crc8_update(crc, buf[len-1]);
            if (crc != 0)
                return 0;
            msg->data_end -= 1;
        }
    } else {
        u_int16_t crc;
        crc = crc16(buf, len-1);
        if (crc == 0 && (buf[len-1] == 0xFF)) {
            msg->data_end -= 3;
        } else {
            crc = crc16_update(crc, buf[len-1]);
            if (crc != 0)
                return 0;
            msg->data_end -= 2;
        }
    }
    msg->has_crc = 0;
    return 1;
}


// prepare a buffer for sending    
void msg_start_extract(BusMessage msg)
{
    msg_add_header(msg);
    msg_add_crc(msg);
    msg->data_pos = msg->data_off-msg->hdr_len;
    msg->data_pos_off = 8;
}

// are there more data to extract?
char msg_extract_more(BusMessage msg)
{
    if (msg->data_pos < msg->data_end)
        return 1;
    if (msg->data_pos > msg->data_end)
        return 0;
    return (msg->data_pos_off > msg->data_end_off);
}

u_int16_t msg_extract_chunk(BusMessage msg, u_int8_t frame_bits)
{
    u_int16_t res = 0;
    u_int8_t *bytes = msg->data+msg->data_pos;
    u_int8_t bits = msg->data_pos_off;

    while(frame_bits) {
        if (bytes >= msg->data+msg->data_end) {
            // if there are residual bits at the end we ignore them
            res = (res << frame_bits) | ((1<<frame_bits)-1);
            break;
        }
        if (frame_bits < bits) {
            bits -= frame_bits;
            res = (res << frame_bits) | (*bytes >> bits) & ((1<<frame_bits)-1);
            break;
        }
        frame_bits -= bits;
        res = (res << bits) | (*bytes & ((1<<bits)-1));

        bits = 8;
        bytes ++;
    }
    msg->data_pos = bytes-msg->data;
    msg->data_pos_off = bits;

    return res;
}

// prepare a buffer for receiving
void msg_start_add(BusMessage msg)
{
    msg->data_off = MSG_MAXHDR-1;
    msg->hdr_len = 0;
    msg->data_end = msg->data_off;
    msg->data_end_off = 8;
    msg->has_crc = 1;
}

void msg_add_chunk(BusMessage msg, u_int8_t frame_bits, u_int16_t data)
{
    u_int8_t *buf = msg->data+msg->data_end;
    u_int8_t bits = msg->data_end_off;
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
            *buf++ = *buf | ((data>>frame_bits) & ((1<<bits)-1));
            bits = 8;
        }
    }
    msg->data_end = buf - msg->data;
    msg->data_end_off = bits;
}

// prepare a buffer to add content to be transmitted
void msg_start_send(BusMessage msg)
{
    msg->hdr_len = 0;
    msg->data_end = msg->data_off;
    msg->data_end_off = 8;
}
void msg_send_data(BusMessage msg, u_int8_t *data, u_int16_t len) // bytes
{
    if (msg->data_end_off != 8) {
        msg->data_end += 1;
        msg->data_end_off = 8;
    }
    memcpy(msg->data+msg->data_end, data, len);
    msg->data_end += len;
    msg->data_end_off = 8;
}
//void msg_send_bits(BusMessage msg, u_int8_t *data, u_int16_t len) // bits 
//{
//}

/*
    def generate_crc(self):
        """
        Add CRC to frame. @frame_len is bits per frame.
        """
        assert self.with_crc is False

        if self._data.length & 7:
            self._data.append(u_int=0,length=8-(self._data.length & 7))
        crc = CRC8 if self._data.len//8 < 8 else CRC16
        crc = crc.new()
        crc.update(self.header.bytes)
        crc.update(self._data.bytes)
        self._data.append(crc.digest())
        self.with_crc = True

    def check_crc(self):
        """
        On an incoming message, remove residual data, check that the CRC is
        correct, and remove it.
        """
        assert self.with_crc
        crc = CRC8 if self._data.length//8 < 10 else CRC16
        crc = crc.new()
        crc.update(self.header.bytes)

        bits = self._data.length
        bits -= (bits&7)
        bits -= 8 # ignore the last byte, for now
        crc.update(self._data[:bits].bytes)
        chop = 0

        # If the frame has been stuffed, the CRC is zero before adding the
        # stuffing. Otherwise it can't be since \xFF is not a fixed point
        # of the CRC function. (Zero is, if the value is zero, which is why
        # we dont use it.)
        if crc.crcValue or self._data[bits:bits+8].bytes != b'\xFF':
            crc.update(self._data[bits:bits+8].bytes)
            bits += 8
        if crc.crcValue:
            return False

        del self._data[bits-8*crc.digest_size:]
        self.with_crc = False
        return True


    def start_extract(self):
        """
        Start extracting chunks from this buffer.
        """
        self.chunk_offset = 0
        if self.with_crc is False:
            self.generate_crc()
        assert self.with_crc is True
        self.hdr_data = BitArray(self.header)

    def extract_chunk(self, frame_bits):
        """
        Extract the @pos'th chunk of @length bits from the data stream.
        """
        offset = self.chunk_offset+frame_bits
        if self.hdr_data is not None:
            res = self.hdr_data[self.chunk_offset:offset]
            if res.length < frame_bits:
                res.append(self._data[:frame_bits-res.length])
                if res.length+self.chunk_offset >= self.hdr_data.length:
                    offset = res.length+self.chunk_offset - self.hdr_data.length
                    self.hdr_data = None
        else:
            res = self._data[self.chunk_offset:offset]
        if res.length == 0:
            return None
        elif res.length < frame_bits:
            res.append(BitArray(int=-1, length=frame_bits-res.length))
            # We stuff with ones, not zeroes, so that the CRC can discover
            # our stuffing later

        self.chunk_offset = offset
        return res.u_int

    def start_add(self):
        assert self.with_crc is None
        assert self._data.length == 0
        assert self.code is None
        self.with_crc = True

    def add_chunk(self,frame_bits, data):
        """
        Feed data into this buffer. (The buffer should initially be new.)

        As soon as the header is complete, it's removed from the input
        stream and available as attributes.

        A missing header is discovered by .code being `None`.

        Call `.check_crc()` when the stream ends.
        """
        self._data += BitArray(u_int=data, length=frame_bits)

        if self.code is None:
            self._gen_code()

    def add_written(self, data):
        """
        Feed data into this buffer. (The buffer should initially be new.)

        This is like `add_chunk` but accepts a BitArray. It's intended for
        switching a writer to a reader, as it needs to feed the data it has
        acquired to a new message.
        """
        self._data += data

        if self.code is None:
            self._gen_code()

    def _gen_code(self):
        frame_len = 3+3
        b = self._data
        if not b.length:
            return
        if not b[0]:
            frame_len += 5
            if b.length <= 8:
                return
            if not b[8]:
                frame_len += 5
        else:
            if b.length <= 3:
                return
            if not b[3]:
                frame_len += 5
        frame_len += 8-(frame_len&7)
        if self._data.length < frame_len:
            return

        b = self._data
        off = 0

        if b[off]:
            self.dst = b[off+1:off+3].u_int
            off += 3
        else:
            self.dst = b[off+1:off+8].u_int+4
            off += 8
        if b[off]:
            self.src = b[off+1:off+3].u_int
            off += 3
        else:
            self.src = b[off+1:off+8].u_int+4
            off += 8

        self.code = b[off:frame_len].u_int
        self.with_crc = True
        del self._data[0:frame_len]

    @property
    def data(self):
        """
        Extract the current data buffer. Must not have a CRC attached.
        """
        assert not self.with_crc
        return self._data.bytes

    def start_send(self):
        """
        Start adding data to be sent to this message.

        The buffer is usually new, but in any case it must not have a CRC.
        """
        assert not self.with_crc
        self.with_crc = False

    def send_data(self, data):
        """
        Add data (bytes) to this message.

        The buffer is stuffed with zeroes if not on a byte boundary.
        """
        assert self.with_crc is False
        if self._data.length & 7:
            self._data.append(u_int=0,length=8-(self._data.length & 7))
        self._data.append(data)

    def send_bits(self, **kw):
        """
        Add an arbitrary number of bits to the buffer.
        """
        assert self.with_crc is False
        self._data.append(**kw)

*/
