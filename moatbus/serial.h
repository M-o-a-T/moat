#ifndef MOATBUS_SERIAL
#define MOATBUS_SERIAL

/*
Serial handler for MoaTbus

This interface describes how to serialize bus frames.

Message Structure:
prio len data CRC16

prio is x01…x04
len is 1 byte if <128, else 2 bytes (MSB|0x80 first)


Code structure:

Call `sb_send` with each message to be transmitted.
On empty serial buffer:
    Call `sb_byte_out`. Send byte if >=0.
On incoming character:
    Call `sb_byte_in`.
    Call `sb_recv` and process if not NULL.
Call `sb_idle` when nothing happened for 1/10 second or so,
periodically, until it returns False.
*/

#include <sys/types.h>

#include "moatbus/message.h"

#ifdef __cplusplus
extern "C" {
#endif

enum SERSTATE {
    S_IDLE = 0,
    S_INIT,
    S_LEN,
    S_LEN2,
    S_DATA,
    S_CRC1,
    S_CRC2,
    S_DONE,
    S_ACK,
};

typedef struct _SerBus {
    BusMessage m_in_first;
    BusMessage m_in;
    u_int16_t crc_in;
    u_int16_t len_in;

    BusMessage m_out;
    BusMessage m_out_last;
    u_int16_t crc_out;

    enum SERSTATE s_in;
    enum SERSTATE s_out;

    u_int16_t err_overflow; // count dropped messages because of business
    u_int16_t err_lost; // incomplete frame
    u_int16_t err_spurious; // char not start of frame
    u_int16_t err_crc; // count dropped messages because of bad CRC
    u_int8_t idle; // counter, to drop partial messages
    u_int8_t ack_out; // counter, to send ACKs
    u_int8_t ack_in; // counter, to process received ACKs
} *SerBus;

// Set up the buffer
SerBus sb_alloc(void);
void sb_free(SerBus sb);

// Queue this message
void sb_send(SerBus sb, BusMessage msg);

// process an incoming serial character
void sb_byte_in(SerBus sb, u_int8_t c);

// call from timeout until False
bool sb_idle(SerBus sb);

// Next char to send? -1 if done
int16_t sb_byte_out(SerBus sb);

// Received a message?
BusMessage sb_recv(SerBus sb);

// Return #acks received (and resets the counter)
u_int8_t sb_recv_ack(SerBus sb);

#ifdef __cplusplus
}
#endif

#endif
