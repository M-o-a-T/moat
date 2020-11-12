#include <stdlib.h>
#include <stdarg.h>
#include <assert.h>

#include "moatbus/common.h"
#include "moatbus/handler.h"
#include "moatbus/message.h"
#include "moatbus/util.h"

enum _S {
    // These wait for the bus to go idle. "settle" is ignored.
    S_ERROR = 0,
    S_WAIT_IDLE = 1,

    // Bus is idle.
    S_IDLE = 2, // "Settle" means that the back-off timer is running
    S_READ = 3,
    S_READ_ACK = 4,
    S_READ_ACQUIRE = 5,
    S_READ_CRC = 6,

    S_WRITE = 10,
    S_WRITE_ACQUIRE = 11,
    S_WRITE_ACK = 12, // entered after READ sees the last bit
    S_WRITE_END = 13, // entered after WRITE_ACK is verified
    S_WRITE_CRC = 14,
};

enum _W {
    W_MORE = 0, // next: MORE/LAST/FINAL
    W_CRC = 1,  // next: READ  # writing the CRC
    W_END = 2,  // next: CRC   # writing the end marker
    W_LAST = 3, // next: END   # writing the last word, < 2^N  # unused
    W_FINAL = 4,// next: CRC   # writing the last word, >= 2^N
};

#ifdef MOAT_USE_REF
#define AREF h->ref,
#define AREF1 h->ref
#else
#define AREF
#define AREF1
#endif

typedef struct _Handler {
    const struct BusCallbacks *cb;
#ifdef MOAT_USE_REF
    void *ref;
#endif

    u_int8_t WIRES;
    u_int8_t MAX;
    u_int8_t BITS;
    u_int8_t LEN;
    u_int8_t LEN_CRC;
    u_int8_t N_END;
    u_int16_t VAL_END;
    u_int16_t VAL_MAX;

    u_int8_t last;
    u_int8_t current;
    u_int8_t intended;
    char settle;

    BusMessage q_first, q_last;
    BusMessage q_prio_first, q_prio_last;
    BusMessage sending;
    BusMessage msg_in;
    u_int16_t val;
    u_int8_t nval;
    u_int8_t want_prio;
    u_int8_t current_prio;
    u_int16_t backoff;
    char no_backoff;

    u_int8_t tries;
    u_int8_t last_zero;
    u_int8_t flapping;
    enum _S state;
    enum _W write_state;

    u_int8_t ack_mask;
    u_int8_t nack_mask;
    u_int8_t ack_masks;
    u_int16_t crc;
    u_int16_t *crc_table;
    u_int8_t cur_chunk[7]; // _LEN entries
    u_int8_t cur_pos; // points beyond the end, i.e. send chunk[pos-1] next
    u_int8_t cur_len; // actually allocated length
} *Handler;

static const u_int8_t LEN[] = {0,0, 7,5,3,3,2}; // messages per chunk;
static const u_int8_t BITS[] = {0,0, 11,14,11,14,11}; // messages per header chunk (11 bits);
static const u_int8_t N_END[] = {0,0, 3,2,1,1,1}; // flips at end;

#define T_SETTLE 2 // Timer A
#define T_BACKOFF 2 // minimum back-off increment after collision
#define T_ZERO 5 // bus downtime between messages
#define T_ERROR 10 // requires bus downtime after an error

static void h_gen_crc(Handler h);
static void h_set_wire(Handler h, u_int8_t bits);
static u_int8_t h_get_wire(Handler h);
static char h_process(Handler h, BusMessage msg);
static void h_debug(Handler h, const char *text, ...);
static void h_report_error(Handler h, enum HDL_ERR err);
static void h_transmitted(Handler h, BusMessage msg, enum HDL_RES res);
static void h_set_timeout(Handler h, u_int8_t val);

static void h_set_state(Handler h, enum _S state);
static void h_reset(Handler h);
static void h_error(Handler h, enum HDL_ERR typ);
static void h_read_crc(Handler h);
static void h_read_next(Handler h, u_int8_t bits);
static void h_set_ack_mask(Handler h);
static void h_read_done(Handler h, char crc_ok);
static void h_send_next(Handler h);
static void h_write_collision(Handler h, u_int8_t bits, char settled);
static char h_write_next(Handler h);
static char h_gen_chunk(Handler h);
static void h_start_writer(Handler h);
static void h_start_reader(Handler h);
static void h_next_step(Handler h, char timeout);
static void h_retry(Handler h, BusMessage msg, enum HDL_RES res);
static void h_timeout_settle(Handler h);
static void h_wire_settle(Handler h, u_int8_t bits);
static BusMessage h_clear_sending(Handler h);
static const char *h_state_name(enum _S state);

// Allocate a bus
BusHandler hdl_alloc(REF u_int8_t n_wires, const struct BusCallbacks *cb)
{
    Handler h = calloc(sizeof(struct _Handler), 1);
#ifdef MOAT_USE_REF
    h->ref = ref;
#endif
    h->cb = cb;

    h->WIRES = n_wires;
    h->MAX = (1<<n_wires)-1;
    h->LEN = LEN[n_wires];
    h->BITS = BITS[n_wires];
    h->N_END = N_END[n_wires];
    h->VAL_END = powi(h->MAX, h->N_END) -1;
    h->VAL_MAX = 1<<h->BITS;
    h->LEN_CRC = (n_wires == 3) ? h->LEN-1 : h->LEN;

    h->last = h->current = cb->get_wire(AREF1);
    h->last_zero = h->current ? h->current+1 : 0;
    h->settle = FALSE;
    h->backoff = T_BACKOFF;
    h->no_backoff = FALSE;

    h->state = S_WAIT_IDLE;
    h_reset(h);
    h_set_timeout(h, T_ZERO);

    h_gen_crc(h);
    return (BusHandler) h;
}

// Free a bus
void hdl_free(BusHandler hdl)
{
    Handler h = (Handler)hdl;
    free(h->crc_table);
    free(h);
}

// CRC calculation. We do that here because we need a fixed-width table
// with as little overhead as possible.

#define POLY 0x583
static inline void h_crc(Handler h, u_int8_t bits)
{
    h->crc = (h->crc >> h->WIRES) ^ h->crc_table[(bits ^ h->crc ^ h->current_prio) & h->MAX];
    // h_debug(h, "CRC add %x => %x\n",bits,h->crc);
}

static u_int16_t _bytecrc_r(u_int16_t crc, u_int16_t poly, u_int8_t depth)
{
    while(depth--) {
        if((crc & 1))
            crc = (crc >> 1) ^ poly;
        else
            crc >>= 1;
    }
    return crc;
}

static void h_gen_crc(Handler h)
{
    u_int8_t max = h->MAX;
    h->crc_table = malloc(max * sizeof(u_int16_t));

    for (u_int16_t b = 0; b <= max; b++)
        h->crc_table[b] = _bytecrc_r(b,POLY,h->WIRES);
}

// Queue+send a message
void hdl_send(BusHandler hdl, BusMessage msg)
{
    Handler h = (Handler)hdl;

    if(!msg->prio) {
        if(h->q_prio_last != NULL)
            h->q_prio_last->next = msg;
        else
            h->q_prio_first = msg;
        h->q_prio_last = msg;
    } else {
        if(h->q_last != NULL)
            h->q_last->next = msg;
        else
            h->q_first = msg;
        h->q_last = msg;
    }
    msg->next = NULL;

    h_send_next(h);
}

// Alert about current wire state
void hdl_wire(BusHandler hdl, u_int8_t bits)
{
    Handler h = (Handler)hdl;

    while(1) {
        h->last_zero = bits ? 0 : 1;
        h->current = bits;
        if(h->state > S_IDLE) {
            h->flapping += 1;
            if(h->flapping > 2*h->WIRES) {
                h_error(h, ERR_FLAP);
                return;
            }
        }
        if(h->settle) {
            if(DEBUG_WIRE)
                h_debug(h, "Change (Settle) %s",h_state_name(h->state));
            h_wire_settle(h, bits);
        } else {
            if(DEBUG_WIRE)
                h_debug(h, "Change (Delay) %s",h_state_name(h->state));
            h_next_step(h, FALSE);
        }

        bits = h_get_wire(h);
        if(bits == h->current)
            break;
    }
    if(h->state > S_IDLE) {
        h->settle = TRUE;
        h_set_timeout(h,T_SETTLE);
    }
}

static void h_wire_settle(Handler h, u_int8_t bits)
{
    /*
    The wire state has changed: now these bits are pulled low.
    */
    if(DEBUG_WIRE)
        h_debug(h, "Wire Settle %02x\n",bits);

    assert(h->state >= S_IDLE);

    if(h->state == S_IDLE) {
        if(bits == 0)
            return;
        if(h->no_backoff && h->sending)
            h_start_writer(h);
        else
            h_start_reader(h);
    }
    else if(h->state == S_WRITE_ACQUIRE) {
        if(bits & (h->want_prio-1)) {
            h_debug(h, "PRIO FAIL %02x %02x",bits,h->want_prio);
            h_start_reader(h);
        }
    }
    else if(h->state == S_WRITE_ACK) {
        if(bits & ~(h->ack_masks | h->last))
            h_error(h, ERR_BAD_COLLISION);
    }
    else if(h->state >= S_WRITE) {
        if(bits & ~(h->intended | h->last))
            h_write_collision(h, bits & ~(h->intended | h->last), FALSE);
    }
}

static void h_set_timeout(Handler h, u_int8_t val)
{
    /*
    Set a timeout.

    If the line is off, add to last_zero so that we can be accurate
    about WAIT_IDLE.
    */
    if(!val && DEBUG_WIRE)
        h_debug(h,"Off");
    if(val <= T_BREAK) {
        h->cb->set_timeout(AREF val);
        return;
    }
    if((val == T_ZERO) && h->last_zero) {
        if(h->last_zero >= T_ZERO)
            val = 1;
        else
            val = T_ZERO-h->last_zero+1;
    }
    if(h->last_zero && (h->last_zero-1 < T_ZERO))
        h->last_zero += val;
    h->cb->set_timeout(AREF val);
}

static void h_set_wire(Handler h, u_int8_t bits)
{
    h->cb->set_wire(AREF bits);
}

static u_int8_t h_get_wire(Handler h)
{
    return h->cb->get_wire(AREF1);
}

static char h_process(Handler h, BusMessage msg)
{
    msg_read_header(msg);
    return h->cb->process(AREF msg);
}

static void h_debug(Handler h, const char *text, ...)
{
    va_list arg;
    va_start(arg, text);
    h->cb->debug(AREF text, arg);
    va_end(arg);
}

static void h_report_error(Handler h, enum HDL_ERR err)
{
    h->cb->report_error(AREF err);
}

static void h_transmitted(Handler h, BusMessage msg, enum HDL_RES res)
{
    h->cb->transmitted(AREF msg, res);
    h->tries = 0;
    h->backoff = (h->backoff > T_BACKOFF*2) ? h->backoff/2 : T_BACKOFF;
}

// The timeout has triggered
void hdl_timer(BusHandler hdl)
{
    Handler h = (Handler)hdl;

    /*
    The timeout has arrived.

    if(the bus has settled, we read the state and act on it. Otherwise)
    the time for the next step has arrived.
    */
    if(h->settle) {
        h->settle = FALSE;
        if(DEBUG_WIRE)
            h_debug(h, "Change Done timer %s",h_state_name(h->state));
        h_timeout_settle(h);
        h->last = h->current;
        if(h->state >= S_WRITE)
            h_set_timeout(h, T_BREAK);
        else if(h->state > S_IDLE)
            h_set_timeout(h, T_ZERO);
    }
    else {
        if(DEBUG_WIRE)
            h_debug(h, "Delay Timer %s",h_state_name(h->state));
        h_next_step(h, TRUE);
        if(h->state > S_IDLE) {
            h->settle = TRUE;
            h_set_timeout(h, T_BREAK+1);
        }
    }
}

static void h_timeout_settle(Handler h)
{
    /*
    State machine: we waited long enough for nothing to happen
    */
    u_int8_t bits = h->current;
    h->flapping = 0;

    if(h->state == S_IDLE) {
        // Bus was idle long enough. Start writing?
        if(h->sending) {
            h->settle = TRUE; // correct because .settle means something different in IDLE;
            h_start_writer(h);
        }
    }
    else if(h->state == S_WRITE_ACQUIRE) {
        if(bits == h->want_prio) {
            h->current_prio = bits;
            h->crc = 0;
            // h_debug(h, "Init CRC %x", h->current_prio);
            h_set_state(h, S_WRITE);
        } else
            h_error(h, ERR_ACQUIRE_FATAL);
    }
    else if(h->state == S_READ_ACQUIRE) {
        if(bits && !(bits&(bits-1))) {
            h->current_prio = bits;
            h->crc = 0;
            // h_debug(h, "Init CRC %x", h->current_prio);
            h_set_state(h, S_READ);
        } else if(!bits)
            h_error(h, ERR_NOTHING);
        else
            h_error(h, ERR_ACQUIRE_FATAL);
    }
    else if(h->state == S_READ) {
        h_crc(h, bits);
        h_read_next(h, bits);
    }
    else if(h->state == S_READ_CRC) {
        h_read_next(h, bits);
    }
    else if(h->state == S_READ_ACK) {
        BusMessage msg = h_clear_sending(h);
        if(bits == h->ack_mask)
            h_transmitted(h, msg, RES_SUCCESS);
        else if(!bits)
            h_retry(h, msg, RES_MISSING);
        else if(bits == h->nack_mask)
            h_retry(h, msg, RES_ERROR);
        else if(bits & ~h->ack_masks) {
            h_error(h, ERR_BAD_COLLISION);
            h_retry(h, msg, RES_FATAL);
        } else // both ACK and NACK are set
            h_retry(h, msg, RES_MISSING);
        h_set_state(h, S_WAIT_IDLE);
    }
    else if(h->state == S_WRITE) {
        if(bits != h->intended)
            h_write_collision(h, bits &~ h->intended, TRUE);
        else
            h_crc(h, bits);
    }
    else if(h->state == S_WRITE_CRC) {
        if(bits != h->intended)
            h_write_collision(h, bits &~ h->intended, TRUE);
    }
    else if(h->state == S_WRITE_ACK) {
        if(bits & ~h->ack_masks)
            h_error(h, ERR_BAD_COLLISION);
        else if(bits != h->ack_mask) {
            h_error(h, ERR_BAD_COLLISION);
            h_write_collision(h, bits &~ h->ack_masks, TRUE);
        } else
            h_set_state(h, S_WRITE_END);
    }
    else if(h->state == S_WRITE_END)
        h_error(h, ERR_CANNOT);

    else
        h_error(h, ERR_UNHANDLED);
}

static void h_retry(Handler h, BusMessage msg, enum HDL_RES res)
{
    h_debug(h, "Retry:%d %s", res, msg_info(msg));
    u_int8_t r;
    if(res == RES_MISSING)
        r = 2;
    else if(res == RES_ERROR)
        r = 4;
    else
        r = 6;
    if(h->tries == 0)
        h->tries = r;
    if(h->tries == 1)
        h_transmitted(h, msg, res);
    else {
        h->tries -= 1;
        msg->next = h->q_first;
        h->q_first = msg;
        if (h->q_last == NULL)
            h->q_last = msg;
        h_send_next(h);
    }
}


static void h_next_step(Handler h, char timeout)
{
    /*
    State machine: something should happen

    if(@timeout is set we got here because of an idle timer.)
    Otherwise, some wire state changed.
    */
    u_int8_t bits = h->current;

    if(h->state < S_IDLE) {
        if(timeout)
            h_error(h, ERR_HOLDTIME);
        else if(h->current)
            h_set_timeout(h, T_OFF);
        else
            h_set_timeout(h, T_ZERO);
    }
    else if(h->state == S_IDLE) {
        // Bus was idle long enough. Start writing?
        if(h->sending)
            h_start_writer(h);
        else if(bits)
            h_start_reader(h);
    }
    else if(h->state < S_WRITE) {
        if(timeout)
            h_error(h, ERR_HOLDTIME);
        // otherwise things are changing, which is what we want
    }
    else if(h->state == S_WRITE_ACQUIRE) {
        if(bits == h->want_prio) {
            h_start_writer(h);
            h_set_state(h, S_WRITE);
        } else {
            // Somebody didn't take their wire down in time
            h_error(h, ERR_ACQUIRE_FATAL);
        }
    }
    else if((h->state == S_WRITE) || (h->state == S_WRITE_CRC)) {
        if(!h_write_next(h)) {}
        else if(bits &~ (h->last | h->intended))
            h_write_collision(h, bits &~ h->intended, FALSE);
        else
            h_set_wire(h, h->intended);
    }
    else if(h->state == S_WRITE_ACK) {
        if(bits &~ (h->last | h->ack_masks))
            h_error(h, ERR_BAD_COLLISION);
        else
            h_set_wire(h, h->ack_mask);
    }
    else if(h->state == S_WRITE_END) {
        h_set_state(h, S_WAIT_IDLE);
    }
    else
        h_error(h, ERR_UNHANDLED);
}


static BusMessage h_clear_sending(Handler h)
{
    BusMessage msg = h->sending;
    h->sending = NULL;
    h->want_prio = 0;
    return msg;
}

static void h_start_reader(Handler h)
{
    /*
    Start reading.
    */
    h_set_state(h, S_READ_ACQUIRE);
}

static void h_start_writer(Handler h)
{
    h->cur_pos = 0;
    h->cur_len = 0;
    h->settle = TRUE;
    msg_start_extract(h->sending);
    h_set_wire(h, h->want_prio);
    h_set_state(h, S_WRITE_ACQUIRE);
    h->write_state = W_MORE;
}

static char h_gen_chunk(Handler h)
{
    /*
    Generate the next couple of states to transmit, depending on the
    state the writer is in.
    */
    assert(h->cur_pos == 0);

    u_int8_t n = 0;
    u_int16_t val = 0; // not required, gcc warning fix

    if(h->write_state == W_MORE) {
        if(! msg_extract_more(h->sending)) {
            h->write_state = W_FINAL;
            while(n < h->N_END)
                h->cur_chunk[n++] = h->MAX;
        } else {
            val = msg_extract_chunk(h->sending, h->BITS);
            if(val >= h->VAL_MAX) {
                if(DEBUG_WIRE)
                    h_debug(h, "Send Residual:x%x",val-h->VAL_MAX);
                h->write_state = W_FINAL;
            } else {
                if(DEBUG_WIRE)
                    h_debug(h, "Send Chunk:x%x",val);
            }
        }
        // else continue in W_MORE
    }
    else if(h->write_state == W_CRC) {
        // Done.
        return FALSE;
    }
    else if((h->write_state == W_END) || (h->write_state == W_FINAL)) {
        // End marker done, send CRC
        val = h->crc;
        // h_debug(h, "CRC is %x",h->crc);
        h->write_state = W_CRC;
        h_set_state(h, S_WRITE_CRC);
    }
    else if(h->write_state == W_LAST)
        h_error(h, ERR_UNUSED);

    if(n == 0) {
        h->cur_pos = (h->write_state == W_CRC) ? h->LEN_CRC : h->LEN;
        while(n < h->cur_pos) {
            u_int16_t v = val / h->MAX;
            u_int8_t p = val - v*h->MAX;
            val = v;
            h->cur_chunk[n++] = p+1;
        }
        assert(!val);
    }

    h->cur_pos = n;
    h->cur_len = n;
    return TRUE;
}

static char h_write_next(Handler h)
{
    /*
    Prepare to write the next piece.
    */
    if(!h->cur_pos && !h_gen_chunk(h)) {
        // switch to reading
        h_set_state(h, S_READ_ACK);
        return FALSE;
    }

    u_int8_t p = h->cur_pos -1;
    h->cur_pos = p;
    u_int8_t res = h->cur_chunk[p];
    assert((0 < res) && (res <= h->MAX));

    h->intended = h->last ^ res;
    return TRUE;
}

static void h_write_collision(Handler h, u_int8_t bits, char settled)
{
    /*
    We noticed a collision when writing.

    @bits: those which I don't want to see.
    @settled: is the current value stable?
    */
    h->want_prio = bits & ~(bits-1);
    // this leaves the lowest-numbered bit turned on
    // thus we separate our prio from the other sender's
    
    // serves no purpose except for logging
    // h_report_error(h, ERR_COLLISION);
    h_debug(h,"WColl x%x %c",bits, settled?'y':'n');

    BusMessage msg;
    if (h->msg_in) {
        msg = h->msg_in;
        msg_resize(msg, (msg_sent_bits(h->sending) >> 3) + 8);
    } else {
        msg = msg_alloc((msg_sent_bits(h->sending) >> 3) + 8);
        h->msg_in = msg;
        msg_start_add(msg);
    }
    u_int16_t off = msg_sent_bits(h->sending) - h->BITS;
    msg_add_in(msg,h->sending, off);
    h->val = 0;
    u_int8_t n = h->cur_len;
    h->nval = 0;
    while(n-- > h->cur_pos+1) {
        h->val = h->val * h->MAX + h->cur_chunk[n]-1;
        h->nval += 1;
        // h_debug(h, "Replay %x",h->cur_chunk[n]-1);
        // not added to CRC: it already is in there
    }

    bits = h->current;
    h_set_state(h, S_READ);
    if(settled) {
        h_crc(h, bits);
        h_read_next(h, bits);
    }
    h->no_backoff = TRUE;
}

static void h_send_next(Handler h)
{
    if(h->sending == NULL) {
        if(h->q_prio_first) {
            h->sending = h->q_prio_first;
            h->q_prio_first = h->sending->next;
            if (!h->q_prio_first)
                h->q_prio_last = NULL;
        } else if(h->q_first) {
            h->sending = h->q_first;
            h->q_first = h->sending->next;
            if (!h->q_first)
                h->q_last = NULL;
        }
    }
    if(h->sending == NULL)
        return;
    if(! h->want_prio) {
        char prio = h->sending->prio;
        if (prio >= h->WIRES) {
            prio -= h->WIRES;
            if(h->no_backoff) {
                h->no_backoff = FALSE;
                h->backoff = T_BACKOFF+2;
            }
            if (prio >= h->WIRES)
                prio = h->WIRES-1;
        }
        h->want_prio = 1<<prio;
    }
    if((h->state == S_IDLE) && !h->settle)
        h_start_writer(h);
}

static void h_read_done(Handler h, char crc_ok)
{
    h->no_backoff = FALSE;
    BusMessage msg_in = h->msg_in;
    h->msg_in = NULL;

    if(!crc_ok) {
        msg_free(msg_in);
        h_report_error(h, ERR_CRC);
        h_set_ack_mask(h);
        if(h->nack_mask) {
            h->ack_mask = h->nack_mask; // oh well;
            h_set_state(h, S_WRITE_ACK);
        } else {
            h_set_state(h, S_WAIT_IDLE);
        }
    } else {
        msg_align(msg_in);
        if(h_process(h, msg_in))
            h_set_state(h, S_WRITE_ACK);
        else {
            // The message is not for us
            h_set_state(h, S_WAIT_IDLE);
        }
    }
}

static void h_set_ack_mask(Handler h)
{
    // This part is somewhat fragile. Cannot be helped.
    u_int8_t bits = h->settle ? h->last : h->current;

    h->ack_mask = (bits == 1) ? 2 : 1;
    h->nack_mask = (h->WIRES == 2) ? (bits ? 0 : 2) : ((bits == 3) || (bits == 1)) ? 4 : 2;
    h->ack_masks = h->ack_mask | h->nack_mask;
    // h_debug(h, "AckBits %02x / %02x due to %02x/%d", h->ack_mask,h->nack_mask,bits,h->settle);
}

static void h_read_next(Handler h, u_int8_t bits)
{
    bits ^= h->last;
    // print("BIT",h->addr,bits-1)
    if(bits == 0) {
        // This may happen when the bus was zero and every writer saw a
        // collision. They all go off the bus instantly, so after
        // settling it's still zero.
        h_error(h, ERR_NOTHING);
        return;
    }
    h->no_backoff = FALSE;

    h->val = h->val * h->MAX + bits-1;
    h->nval += 1;
    if(h->state == S_READ_CRC) {
        if(h->nval == h->LEN_CRC) {
            // h_debug(h, "CRC: local %x vs. remote %x", h->crc, h->val);
            h_read_done(h, h->val == h->crc);
        }
    }
    else { // S_READ
        if((h->nval == h->N_END) & (h->val == h->VAL_END))
            h_read_crc(h);
        else if(h->nval == h->LEN) {
            if(h->val >= h->VAL_MAX + (1<<(h->BITS-8))) {
                h_error(h, ERR_CRC); // eventually. We hope.
            } else if(h->val >= h->VAL_MAX) {
                if(DEBUG_WIRE)
                    h_debug(h, "Add Residual x%x", h->val-h->VAL_MAX);
                msg_add_chunk(h->msg_in, h->val-h->VAL_MAX, h->BITS-8);
                h_read_crc(h);
            } else {
                if(DEBUG_WIRE)
                    h_debug(h, "Add Chunk x%x",h->val);
                msg_add_chunk(h->msg_in, h->val, h->BITS);
                h->nval = 0;
                h->val = 0;
            }
        }
    }
}

static void h_read_crc(Handler h)
{
    /*
    Switch to reading the CRC.
    */
    h->nval = 0;
    h->val = 0;
    h_set_state(h, S_READ_CRC);
}

static void h_error(Handler h, enum HDL_ERR typ)
{
    if (h->state == S_ERROR)
        return;

    if((typ == ERR_HOLDTIME) && !h->current) {
        if(h->state < S_IDLE)
            h_set_state(h, S_IDLE);
        else
            h_set_state(h, S_WAIT_IDLE);
        return;
    }

    if(typ < 0) {
        if(h->backoff < 3*T_BACKOFF)
            h->backoff *= 1.5+random();
        else
            h->backoff *= 1.2;
    }
    h_debug(h, "Error %s %d %d", h_state_name(h->state), typ, h->backoff);

    h_report_error(h, typ);
    h_reset(h);
    if((typ <= ERR_FATAL) && h->sending) {
        BusMessage msg = h_clear_sending(h);
        h_transmitted(h, msg,RES_FATAL);
        h_set_state(h, S_WAIT_IDLE);
    }
    else if((0 < typ) && (typ < ERR_FATAL))
        h_set_state(h, S_ERROR);
    else
        h_set_state(h, S_WAIT_IDLE);

}

static void h_reset(Handler h)
{
    h->intended = 0;

    h->cur_pos = 0;
    h->cur_len = 0;
    h->ack_mask = 0;
    if (h->msg_in == NULL) {
        h->msg_in = msg_alloc(6);
    }
    msg_start_add(h->msg_in);
    h->val = 0;
    h->nval = 0;
    h->settle = FALSE;
}

static void h_set_state(Handler h, enum _S state)
{
    if(state == h->state)
        return;

    if(DEBUG_WIRE ||
        ((state >= S_READ) != (h->state >= S_READ)) ||
        ((state >= S_WRITE) != (h->state >= S_WRITE)) )
        // h_debug(h, "SetState %s",h_state_name(state));


    if((state < S_WRITE) && (h->state >= S_WRITE)) {
        // stop writing == do not set any wires
        h_set_wire(h, 0);
    }

    if((state == S_READ_ACK) || (state == S_WRITE_ACK))
        h_set_ack_mask(h);

    if((state == S_READ_ACQUIRE) || (state == S_WRITE_ACQUIRE))
        h->no_backoff = FALSE;

    if(state == S_IDLE) {
        // entering IDLE: wait some more
        assert(!h->current);
        h->state = state;
        h->settle = TRUE;
        h_set_timeout(h, T_BREAK+1+((h->no_backoff && h->sending) ? 0 : h->backoff));
    }
    else if((state < S_IDLE) & (h->state > S_IDLE)) {
        // Stop active work. Reset our machinery appropriately.
        h->state = state;
        h_reset(h);
        h_send_next(h);
        if(h->current)
            h_set_timeout(h, T_OFF);
        else if(state == S_ERROR)
            h_set_timeout(h, T_ERROR);
        else
            h_set_timeout(h, T_ZERO);
    }
    else
        h->state = state;
}

static const char *h_state_name(enum _S state)
{
    if(state == S_ERROR) return "ERROR";
    if(state == S_WAIT_IDLE) return "WAIT_IDLE";
    if(state == S_IDLE) return "IDLE";
    if(state == S_READ) return "READ";
    if(state == S_READ_ACK) return "READ_ACK";
    if(state == S_READ_ACQUIRE) return "READ_ACQUIRE";
    if(state == S_READ_CRC) return "READ_CRC";
    if(state == S_WRITE) return "WRITE";
    if(state == S_WRITE_ACQUIRE) return "WRITE_ACQUIRE";
    if(state == S_WRITE_ACK) return "WRITE_ACK";
    if(state == S_WRITE_END) return "WRITE_END";
    if(state == S_WRITE_CRC) return "WRITE_CRC";
    return "???";
}
