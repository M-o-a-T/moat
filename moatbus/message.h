/*
Message structure for MoatBus
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
    char has_crc;
};
#define MSG_MAXHDR 3
#define MSG_MAXCRC8 7 // CRC16 when larger
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
// Length of the message, excluding header and CRC
u_int16_t msg_length(BusMessage msg);

// copy the first @off bits to a new message
BusMessage msg_copy_bits(BusMessage msg, u_int8_t off);

// ensure there's a CRC
void msg_add_crc(BusMessage msg);

// check CRC, ensure there's no CRC
char msg_check_crc(BusMessage msg);

// prepare a buffer for sending
void msg_start_extract(BusMessage msg);
// are there more data to extract?
char msg_extract_more(BusMessage msg);
// extract a frame_bits wide chunk
u_int16_t msg_extract_chunk(BusMessage msg, u_int8_t frame_bits);

// prepare a buffer for receiving
void msg_start_add(BusMessage msg);
// received @frame_bits of data
void msg_add_chunk(BusMessage msg, u_int8_t frame_bits, u_int16_t data);

// prepare a buffer to add content to be transmitted
void msg_start_send(BusMessage msg);
// add bytes, filling incomplete bytes with zero
void msg_send_data(BusMessage msg, u_int8_t *data, u_int16_t len);
// add bits
void msg_send_bits(BusMessage msg, u_int8_t *data, u_int16_t off, u_int16_t len); // bits

