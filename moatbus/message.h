/*
Message structure for MoatBus

This interface mostly mimics message.py
*/

#include <sys/types.h>

struct _BusMessage {
    struct _BusMessage *next; // for chaining buffers

    // if all three are zero the data is in the message
    // // otherwise the header is authoritative, write to the message
    int8_t src; // Server: -1…-4
    int8_t dst; // Server: -1…-4
    u_int8_t code;

    u_int8_t *data;
    u_int16_t data_max; // buffer length, bytes
    u_int16_t data_off; // Offset for content (header is before this)

    u_int16_t data_pos; // current read position: byte offset
    u_int8_t data_pos_off; // current read position: non-filled bits
    u_int16_t data_end; // current write position: byte offset
    u_int8_t data_end_off; // current write position: non-filled bits
    u_int8_t hdr_len; // Length of header. 0: values are in the struct
};
#define MSG_MAXHDR 3
#define MSG_MINBUF 30

typedef struct _BusMessage *BusMessage;

// Allocate an empty message
BusMessage msg_alloc(u_int16_t maxlen);
// Free a message
void msg_free(BusMessage msg);
// Increase max buffer size
void msg_resize(BusMessage msg, u_int16_t maxlen);

// Add header bytes to the message
void msg_add_header(BusMessage msg);
// Move header data from the message to data fields
void msg_read_header(BusMessage msg);

// Start address of the message (data only)
u_int8_t *msg_start(BusMessage msg);
// Length of the message, excluding header (bytes)
u_int16_t msg_length(BusMessage msg);
// Length of the complete message (bits)
u_int16_t msg_bits(BusMessage msg);

// copy the first @off bits to a new message
BusMessage msg_copy_bits(BusMessage msg, u_int8_t off);

// sender

// prepare a buffer to add content to be transmitted
void msg_start_send(BusMessage msg);
// add bytes, filling incomplete bytes with zero
void msg_send_data(BusMessage msg, u_int8_t *data, u_int16_t len);

// prepare a buffer for sending
void msg_start_extract(BusMessage msg);
// are there more data to extract?
char msg_extract_more(BusMessage msg);
// extract a frame_bits wide chunk.
// at the end of the message, fill with zeroes if <8 bits are missing
//    otherwise align to 8-bit, return |(1<<frame_bits)
u_int16_t msg_extract_chunk(BusMessage msg, u_int8_t frame_bits);

// receiver

// prepare a buffer for receiving
void msg_start_add(BusMessage msg);
// received @frame_bits of data
void msg_add_chunk(BusMessage msg, u_int16_t data, u_int8_t frame_bits);

// remove @bits of data from the end, return contents
u_int16_t msg_drop(BusMessage msg, u_int8_t frame_bits);
// remove residual bits
void msg_align(BusMessage msg);

// deprecated, only present for fakebus/test_handler_crc.c
// add zero filler plus 1-bit "added more than 8 bits" flag + CRC
void msg_fill_crc(BusMessage msg, u_int8_t frame_bits, u_int16_t crc, u_int8_t crc_bits);
