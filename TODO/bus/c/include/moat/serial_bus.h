#ifndef MOATBUS_SERIAL
#define MOATBUS_SERIAL

/*
Serial handler for MoaTbus

This interface describes how to serialize bus frames.

Message Structure:
prio len data CRC16

prio is x01,x02,x81,x82
len is 1 byte if <128, else 2 bytes (MSB|0x80 first)


Code structure:

Call `sb_send` with each message to be transmitted.
Call `sb_recv` to fetch and process incoming messages.
Call `sb_getchar` to process incoming non-message characters.

On empty serial buffer:
    Call `sb_byte_out`. Send byte if >=0.
On incoming character:
    Call `sb_byte_in`.
    Call `sb_recv` and process if not NULL.
Call `sb_idle` when nothing happened for 1/10 second or so,
periodically, until it returns False.
*/

#include <sys/types.h>

#ifndef MOAT_SER_INBUF_SIZE
#define MOAT_SER_INBUF_SIZE 0
#endif

#if MOAT_SER_INBUF_SIZE
#include "tsrb.h"
#endif

#include "moatbus/message.h"

#ifdef __cplusplus
extern "C" {
#endif

enum SERSTATE {
    S_IDLE = 0,
    S_UTF8,
    S_INIT,
    S_LEN,
    S_LEN2,
    S_DATA,
    S_CRC1,
    S_CRC2,
    S_DONE,
    S_ACK,
};
enum SERERRROR {
    S_ERR_CRC = 1,
    S_ERR_MEM = 2,
    S_ERR_OVERRUN = 4,
    S_ERR_TIMER = 8,
};

typedef void (*ser_recv_t)(BusMessage msg);

typedef struct _SerBus {
    uart_t serial;
    BusMessage m_in; // incoming
    BusMessage m_in_proc; // being processed
    u_int16_t crc_in;
    u_int16_t len_in;

    u_int16_t crc_out;

    enum SERSTATE s_in;

#if MOAT_SER_INBUF_SIZE
    struct tsrb inbuf;
    uint8_t in_buf[MOAT_SER_INBUF_SIZE];
#endif

    mutex_t send_lock;

    mutex_t recv_lock;
    cond_t recv_wait;
    ztimer_t recv_timeout;

    uint16_t errors; // count errors
    uint8_t errflag; // flags which errors have been seen
    uint8_t prio; // of incoming message
} *SerBus;

// Set up the buffer
void sb_init(SerBus sb, uart_t serial);
void sb_deinit(SerBus sb);

// Queue this message
void sb_send(SerBus sb, BusMessage msg);

// process an incoming serial character
void sb_byte_in(SerBus sb, u_int8_t c);

#if MOAT_SER_INBUF_SIZE
// get a char from the non-packetized-things buffer
int16_t sb_getchar(SerBus sb, bool block);
#endif

// Next char to send? -1 if done
int16_t sb_byte_out(SerBus sb);

// Received a message?
BusMessage sb_recv(SerBus sb, bool blocking);

// Return #acks received (and resets the counter)
u_int8_t sb_recv_ack(SerBus sb);

#ifdef __cplusplus
}
#endif

#endif
