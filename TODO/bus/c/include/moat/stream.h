#ifndef MOAT_STREAM
#define MOAT_STREAM

#include "moat/message.h"
#include "moat/timer.h"

enum StreamEvent {
  SE_ok = 0,
  SE_wait = 1, // got a not-ready message
  SE_disc = 2, // other side disconnected
  SE_err_min = 3,
  SE_timeout = 3, // other side didn't react
  SE_err_remote = 4, // remote complained
};

enum StreamState {
  ST_idle = 0,
  ST_disconnect = 2, // other side disconnected
  ST_connect = 1, // got a not-ready message
  ST_run = 3,
  ST_timeout = 4, // other side didn't react
};

typedef void (*stream_recv_t)(void *user, BusMessage msg, uint8_t offset);
typedef void (*stream_event_t)(void *user, StreamEvent err, BusMessage msg);

struct _Stream {
    struct mtick tick;
    struct _BusMessage *sendq_first;
    struct _BusMessage *sendq_last;
    uint8_t sendq_maxlen;
    uint8_t sendq_len;
    uint8_t seq_ack;  // last message ack'd by the other side
    uint8_t seq_send; // next message to send
    uint8_t bit_seen; // messages selectively acked by the other side
    // #messages in sendq == seq_send-seq_ack
    //
    // message destination
    uint8_t r_dest;
    uint8_t r_code;

    uint8_t seq_recv; // next incoming message
    uint8_t seq_r_ack; // seq_recv we last sent to the remote side
    struct _BusMessage *recvq_first; // for selective whatever

    uint8_t c_no_recv; // timer steps without correct incoming data
    uint8_t c_timeout; // timeout counter for failure propagation

    // hook to process an incoming message
    stream_recv on_data;
    stream_err on_event;
    void *user;

    enum StreamState state;
    bool r_ready; // remote accepts data
    bool ready; // I accept data
};

typedef struct _Stream *MoatStream;

// Management
MoatStream stream_alloc();
void stream_init(MoatStream stream);
void stream_set_user(MoatStream stream, stream_recv_t on_data, stream_err_t on_error, void *user);
void stream_set_dest(MoatStream str, uint8_t dest, uint8_t code);
void stream_start(MoatStream stream);
void stream_stop(MoatStream stream);
void stream_free(MoatStream stream);

void stream_set_ready(MoatStream stream, bool ready);

// submit an incoming message
void msg_recv(MoatStream str, BusMessage msg);

// send a message
BusMessage stream_prep(MoatStream str, msglen_t maxlen);
void stream_send(MoatStream str, BusMessage msg);

// timer tick
BusMessage stream_timer(MoatStream str);

#endif
