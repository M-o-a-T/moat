#ifndef MOATBUS_SERIAL
#define MOATBUS_SERIAL

/*
Serial handler for MoatBus

This interface serializes bus frames.

Structure:
0x01 len data CRC16
0x02 … same for lower-priority messages

Anything else is supposed to be ASCII / UTF-8
Len is extended to two bytes if bit 7 is set
*/

#include <sys/types.h>

#include "moatbus/message.h"

enum SERSTATE {
    S_IDLE = 0,
    S_INIT,
    S_LEN,
    S_LEN2,
    S_DATA,
    S_CRC1,
    S_CRC2,
    S_DONE,
};

typedef struct _SerBus {
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
void sb_send(SerBus sb, BusMessage msg, u_int8_t prio);

// Queue sending an ACK
void sb_send_ack(SerBus sb);

// process an incoming serial character
void sb_char_in(SerBus sb, u_int8_t c);

// Send char? <0=no
int16_t sb_char_out(SerBus sb);

// Received message?
BusMessage sb_recv(SerBus sb, u_int8_t *prio);

// Received some ACKs?
u_int8_t sb_recv_ack(SerBus sb);

// call from timeout until False
char sb_idle(SerBus sb);

#endif
