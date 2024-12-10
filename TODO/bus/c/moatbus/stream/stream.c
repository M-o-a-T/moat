#include "moatbus/stream.h"

#define T_STEPS 3 // timer loop steps until a timeout condition
#define T_ERROR 5 // timeout conditions until the error is deemed fatal

enum StreamControl {
   S_is_Ctrl = 0x80,  // if clear this is a data frame.
   S_is_Flow = 0x40,
   S_is_Reply = 0x20,
   S_is_Ready = 0x10,
   S_is_Push = 0x08,

   // Control
   S_Stop = 0x0,
   S_Start = 0x1,
   S_Error = 0x7,
};

// returns true if a <= b <= c, mod 8|128
static inline bool seq_consecutive(MoatStream str, uint8_t a, uint8_t b, uint8_t c)
{
	b = (b-a)&0x07;
	c = (c-a)&0x07;
	return b <= c;
}

static bool stream_timer(MTICK tick)
{
	MoatStream str = (MoatStream)tick;
	if(!str->sendq_len)
		return false;
	
}

void stream_send(MoatStream str, BusMessage m)
{
	m->src = my_addr;
	m->dst = str->dest;
	m->code = str->code;
	send_msg(m);
}

static void xmit1(MoatStream str, uint8_t data)
{
	BusMessage m = msg_alloc(1);
	if(m == nullptr)
		break;
	msg_add_byte(S_is_Ctrl|S_Stop|S_is_Push);
	stream_send(str,m);
}

static void xmit2(MoatStream str, uint8_t data, uint8_t aux)
{
	BusMessage m = msg_alloc(2);
	if(m == nullptr)
		break;
	msg_add_byte(S_is_Ctrl|S_Stop|S_is_Push);
	msg_add_byte(aux);
	stream_send(str,m);
}

static void xmit12(MoatStream str, uint8_t data, uint8_t aux)
{
	if(aux)
		xmit2(str, data, aux);
	else
		xmit1(str, data);
}

static void xmit2s(MoatStream str, uint8_t data, uint8_t aux, const char *data)
{
	uint8_t len = strlen(data);
	BusMessage m = msg_alloc(2+len);
	if(m == nullptr)
		break;
	msg_add_byte(m, S_is_Ctrl|S_Stop|S_is_Push);
	msg_add_byte(m, aux);
	msg_add_data(m, data, len);
	stream_send(str,m);
}

static uint8_t get_srej(MoatStream str)
{
	uint8_t off = 0;
	uint8_t cur = (str->seq_recv+1)&0x07;
	uint8_t bit = 1;
	BusMessage recv = str->recv_first;
	while(recv) {
		while((bit < 8) && (cur != (recv->data[recv->data_off]>>4)&0x07)) {
			bit++;
			cur = (cur+1)&0x07;
		}
		if(bit >= 8)
			break;
		off |= bit;
		recv = recv->next;
	}
	return off;
}

static bool stream_run_timer(MoatStream str)
{
	switch(str->state) {
	case ST_connect:
		BusMessage m = msg_copy(str->sendq_first);
		if(m)
			stream_send(m);
		break;
	case ST_disconnect:
		xmit1(str, S_is_Ctrl|S_Stop|S_is_Push);
		break;
	case ST_run:
		if(str->sendq_len)
			break;
		// fall thru
	case ST_idle:
		str->timer_on = false;
		return false;
	case ST_timeout:
		break;
	}

	uint8_t srej = get_srej(str);
	if(srej) {
		xmit2(str, S_is_Ctrl| S_is_flow | (str->ready ? S_is_Ready : 0) | seq->recv, srej);
	} else
		xmit1(str, S_is_Ctrl| S_is_flow | (str->ready ? S_is_Ready : 0) | seq->recv);
	return true;
}

static inline uint8_t seq_up(MoatStream str, uint8_t seq)
{
	seq += 1;
	return seq & 0x07;
}

MoatStream stream_alloc()
{
	MoatStream stream = malloc(sizeof(*stream));
	stream_init(stream);
	return stream;
}

static void null_data(void *user, BusMessage msg, uint8_t offset)
{
	msg_free(msg);
}

static void null_event(void *user, StreamEvent err, BusMessage msg)
{
	if(msg != nullptr)
		msg_free(msg);
}

void stream_init(MoatStream stream)
{
	memset(stream,0,sizeof(stream));
	str->on_data = null_data;
	str->on_event = null_event;
}

BusMessage stream_prep_start(MoatStream str, msglen_t len)
{
	msg = msg_alloc(1+len);
	if(msg != nullptr)
		msg_add_byte(msg, S_is_Ctrl|S_Start);
	return msg;
}

void stream_set_dest(MoatStream str, uint8_t dest, uint8_t code)
{
	str->r_dest = dest;
	str->r_code = code;
}

void stream_set_proc(MoatStream str, stream_recv_t on_data, stream_err_t on_error, void *user)
{
	str->on_data = on_data;
	str->on_error = on_error;
	str->user = user;
}

void stream_start(MoatStream str, BusMessage msg)
{
#ifndef NDEBUG
	if(str->state >= ST_connect) {
		msg_free(msg);
		return;
	}
#endif
	if(msg == nullptr) {
		BusMessage msg = msg_alloc(1+len);
		if(msg == nullptr)
			return;
		msg_add_byte(msg, S_is_Ctrl|S_Start);
	}
	str->sendq_first = msg;
	stream_send(str, msg);
}

void stream_stop(MoatStream str)
{
	if(str->state <= ST_disconnect)
		return;
	str->state = ST_disconnect;
	xmit1(str, S_is_Ctrl|S_stop);
}

void stream_done(MoatStream str)
{
	if(str->sendq_last) { // ops
		BusMessage m = str->sendq_first;
		while(m) {
			BusMessage m2 = m->next;
			msg_free(m);
			m = m2;
		}
	} else if(str->sendq_first) { // startup
		msg_free(str->sendq_first);
	}

	BusMessage m = str->recvq_first;
	while(m) {
		BusMessage m2 = m->next;
		msg_free(m);
		m = m2;
	}

	str->sendq_first = nullptr;
	str->sendq_last = nullptr;
	str->recvq_first = nullptr;
}

void stream_free(MostAtream str)
{
	stream_done(str);
	free(str)
}

static void process_ack(MoatStream str, uint8_t d, uint8_t d2)
{
	BusMessage msg;
	uint8_t m = d & 0x07;

	if(!seq_consecutive(str->seq_ack, m, str->seq_send)) {
		xmit2s(str, S_is_Ctrl|S_Error|S_is_Reply, d, "rseq");
		return;
	}
	bool ordy = str->r_ready;
	str->r_ready = !!(d & S_is_Ready);
	while(m != str->seq_ack) {
#ifndef NDEBUG
		if(str->sendq_first == nullptr || str->sendq_len == 0) {
			xmit2s(str, S_is_Ctrl|S_Error|S_is_Push, d, "smsg");
			return;
		}
#endif
		str->seq_ack = (str->seq_ack + 1) & 0x07;

		msg = str->sendq_first;
		str->sendq_first = msg->next;
		if(msg->next == nullptr)
			str->sendq_last = nullptr;
		str->sendq_len -= 1;
		msg_free(msg);
		str->c_no_recv = 0;
	}
	if(ordy || !str->r_ready)
		return;
	msg = str->sendq_first;
	uint8_t b = str->bit_seen;
	while(m != str->seq_send) {
#ifndef NDEBUG
		if(msg == nullptr) {
			xmit2s(str, S_is_Ctrl|S_Error|S_is_Push, d, "smsg2");
			return;
		}
#endif
		if(!(b & 1)) {
			msg->data[msg->data_pos] = (m<<4) | str->seq_recv;
			BusMessage m = msg_copy(msg);
			if(m == nullptr)
				return;
			send_msg(m);
			str->seq_r_ack = str->seq_recv;
		}
		b >>= 1;
		msg = msg->next;
	}
}

static void take_stream_down(MoatStream str, enum StreamState st)
{
	stream_done(str);
	str->state = ST_idle;
}

static void take_stream_up(MoatStream str)
{
	stream_done(str);
	str->seq_ack = 0;
	str->seq_send = 0;
	str->seq_recv = 0;
	str->state = ST_run;
}

// incoming message
void stream_recv(MoatStream str, BusMessage msg)
{
	if(msg->data_pos == msg->data_len)
		return; // no data, no glory

	uint8_t d = *msg->data[msg->data_pos];

	if((d & S_is_Reply) && (d & S_is_Push) && (str->state == ST_timeout)) {
		str->state = ST_run;
		str->c_timeout = 0;
	}
	if(!(d & S_is_Ctrl)) { // data
		if(str->state < ST_run)
			return;

		process_ack(str,d);
		if(((d >> 4) & 0x07) == msg->seq_recv) {
			// process this
			msg->data_pos += 1;
			str->seq_recv += 1;
			(*str->on_data)(msg, str->user);
			while(true) {
				msg = str->recv_first;
				if(msg == nullptr)
					break;
				msg = str->recv_first;
				d = *msg->data[msg->data_pos];
				if(((d >> 4) & 0x07) != msg->seq_recv)
					break;

			}
		}
	} else if(d & S_is_Flow) { // connected
		if(str->state < ST_run)
			return;

		uint8_t d2 = 0;

		if(msg->data_pos < msg->data_len-1)
			d2 = msg->data[msg->data_pos+1];
		process_ack(str,d);

	} else { // setup/teardown
		switch(d & 0x07) {
		case S_Start:
			switch(str->state) {
			case ST_idle:
				if(d & S_is_Reply) {
					// Owch, client/server mismatch?
					xmit1(str, S_is_Ctrl|S_is_Push|S_is_Reply|S_Stop);
					return;
				}
				xmit1(str, S_is_Ctrl|S_is_Reply|S_Start|(d&S_is_Push));
				take_stream_up(str);
				break;
			case ST_disconnect:
				// nope nope nope
				return;
			case ST_connect:
				if(!(d & S_is_Reply)) {
					// Owch, client/server mismatch?
					xmit1(str, S_is_Ctrl|S_is_Push|S_is_Reply|S_Stop);
					return;
				}
				take_stream_up(str);
				break;

			default: // run
				return; // no-op, we hope
			}
		case S_Stop:
			switch(str->state) {
			case ST_idle:
			case ST_disconnect:
			case ST_connect:
				if(d & S_is_Reply)
					return;
				xmit1(str, S_is_Ctrl|S_is_Reply|S_Stop|(d&S_is_Push));
				break;
			default:
				take_stream_down(str, ST_idle);
				break;
			}
		case S_Error:
			(*str->on_error)(str,  SE_err_remote, msg)
			take_stream_down(str, ST_idle);
		}
	}
	str->c_no_recv = 0;
}

BusMessage stream_prep(MoatStream str, msglen_t maxlen)
{
#if 0
	if(!str->r_ready)
		return nullptr;
#endif
	if(str->sendq_len >= 7)
		return nullptr;

	BusMessage msg = msg_alloc(maxlen+1);
	msg_add_byte(msg,0); // filled later
	return msg;
}

void stream_send(MoatStream str, BusMessage msg)
{
	if(str->sendq_first)
		str->sendq_last->next = msg;
	else
		str->sendq->first = msg;
	str->sendq_last = msg;

	str->seq_r_ack = str->seq_recv;
	str->seq_send += 1;

	if(str->sendq_first)
		str->sendq_last->next = msg;
	else
		str->sendq_first = msg;
	str->sendq_last = msg;
	str->sendq_len += 1;

	if(!str->r_ready)
		return;
	if(str->state != ST_run)
		return;

	// TODO set Push bit?
	msg->data[msg->data_pos] = (str->seq_send << 4) | str->seq_recv;
	m = msg_copy(m);
	if(m == nullptr)
		return;
	send_msg(m);
}

void stream_set_ready(MoatStream stream, bool ready)
{
	if(ready == str->ready)
		return;
	str->ready = ready;

	uint8_t d = S_is_Ctrl|S_is_flow|str->seq_recv;
	uint8_t srej = get_srej(str);
	if(str->ready)
		d |= S_Ready;
	xmit12(str, d, srej);

}

// timer tick
BusMessage stream_timeout(MoatStream str)
{
	if(str->c_no_recv++ < T_STEPS) {
		// TODO do we check seq_r_ack early?
		return;
	}
	str->c_no_recv = 0;
	if(++str->c_timeout >= T_ERROR) {
		xmit2s(str, S_is_Ctrl|S_Error, d, "time");
		xmit2s(str, S_is_Ctrl|S_Stop|S_is_Push, d, "time");
		str->state = ST_idle;
		return;
	}
	switch(str->state) {
	case ST_idle:
		return; // ???
	case ST_disconnect:
		xmit1(str, S_is_Ctrl|S_Stop|S_is_Push);
		break;
	case ST_connect:
		xmit1(str, S_is_Ctrl|S_Start|S_is_Push);
		break;
	default:
		if(str->seq_recv == str->seq_r_ack && str->seq_ack == seq_send) {
			str->c_timeout = 0;
			return;
		}
		uint8_t d = S_is_Ctrl|S_is_flow|str->seq_recv;
		uint8_t srej = get_srej(str);
		if(str->ready)
			d |= S_Ready;
		if(str->seq_recv != str->seq_r_ack)
			d |= S_is_Push;

		xmit12(str, d, srej);

		str->seq_r_ack = str->seq_recv;
		break;
	}
}


/*
 * Timeout prototypes
 */
static void x75_T1 (MoatStream state);
static void x75_T3 (MoatStream state);

static char *x75_sname[]=
	{"S_free", "S_down", "S_await_up", "S_await_down", "S_up", "S_recover",};
/*
 * State change.
 */

static void
x75_setstate (MoatStream state, x75_status status)
{

	if (state->debug & 0x02)
		printf ("%sx75.%d Setstate %d/%s -> %d/%s\n", KERN_DEBUG,state->debugnr, state->status, x75_sname[state->status], status, x75_sname[status]);
	if(state->status != S_free) {
		state->status = status;
		if(state->status == S_down)
			state->errors = 0;
	}
}

/*
 * Macros for timeouts
 */

#ifdef OLD_TIMEOUT

#define stop_T(xx,er) do {			\
	if(state->T##xx) { 				\
		state->T##xx = 0; 			\
		if(state->debug & 0x08)		\
			printf("%sStop%d T"#xx" %d\n",KERN_DEBUG,state->debugnr,__LINE__);	\
		untimeout((void *)x75_T##xx,state); \
	}           					\
	(er)=0;							\
	} while(0)

#define start_T(xx,er) do { 		\
	if(! state->T##xx) { 			\
		state->T##xx = 1; 			\
		if(state->debug & 0x08) 		\
			printf("%sStart%d T"#xx" %d %d\n",KERN_DEBUG,state->debugnr,state->RUN_T##xx, __LINE__);	\
		timeout((void *)x75_T##xx,state,(state->RUN_T##xx * HZ) / 10); 	\
	}           					\
	(er)=0;							\
	} while(0)

#define restart_T(xx,er) do {		\
	if(state->T##xx) 				\
		untimeout((void *)x75_T##xx,state); \
	state->T##xx = 1; 				\
	if(state->debug & 0x08)			\
		printf("%sRestart%d T"#xx" %d %d\n",KERN_DEBUG,state->debugnr,state->RUN_T##xx, __LINE__);	\
	timeout((void *)x75_T##xx,state,(state->RUN_T##xx * HZ) / 10); 	\
	} while(0)

#else /* NEW_TIMEOUT */

#define stop_T(xx,er) do {			\
	if(state->T##xx) { 				\
		state->T##xx = 0; 			\
		if(state->debug & 0x08)		\
			printf("%sStop%d T"#xx" %d\n",KERN_DEBUG,state->debugnr,__LINE__);	\
		untimeout(state->timer_T##xx); \
	}           					\
	(er)=0;							\
	} while(0)

#define start_T(xx,er) do { 		\
	if(! state->T##xx) { 			\
		state->T##xx = 1; 			\
		if(state->debug & 0x08) 		\
			printf("%sStart%d T"#xx" %d %d\n",KERN_DEBUG,state->debugnr,state->RUN_T##xx,__LINE__);	\
		state->timer_T##xx = timeout((void *)x75_T##xx,state,(state->RUN_T##xx * HZ) / 10); 	\
	}           					\
	(er)=0;							\
	} while(0)

#define restart_T(xx,er) do {		\
	if(state->T##xx) 				\
		untimeout(state->timer_T##xx); \
	state->T##xx = 1; 				\
	if(state->debug & 0x08)			\
		printf("%sRestart%d T"#xx" %d %d\n",KERN_DEBUG,state->debugnr,state->RUN_T##xx,__LINE__);	\
	state->timer_T##xx = timeout((void *)x75_T##xx,state,(state->RUN_T##xx * HZ) / 10); 	\
	(er)=0;							\
	} while(0)

#endif
/*
 * Send indication up.
 */
#define msg_up(state,ind,add) (*state->state)(state->ref,ind,add)

/*
 * Clear state machine -- connection down.
 */
static int
kill_me (MoatStream state, char ind)
	/* Abort the connection, reset everything */
{
	int err2 = 0;
	x75_status oldstate = state->status;

	S_flush (&state->I);
	S_flush (&state->UI);
	x75_setstate(state, S_down);
	stop_T (1, err2);
	stop_T (3, err2);
	if (ind != 0 && oldstate != S_free && oldstate != S_down)
		msg_up (state, ind, 0);

	return 0;
}

/*
 * Clear exception conditions.
 */
static int
clr_except (MoatStream state)
{
	state->RNR = 0;
	state->sentRR = 1;
	state->inREJ = 0;
	state->ack_pend = 0;

	return 0;
}

/*
 * Flush I queue.
 */
static int
flush_I (MoatStream state)
{
	S_flush (&state->I);
	state->v_r = state->v_s = state->v_a = 0;
	if(state->backenable)
		(*state->backenable) (state->ref);

	return 0;
}

/*
 * Start retransmission.
 */
static int
retransmit (MoatStream state)
{
#if 0
	if (state->flush != NULL && state->v_s != state->v_a)
		(*state->flush) (state->ref);
#endif

	state->v_s = state->v_a;

	return 0;
}

/*
 * Send 3-byte header. Actually enqueue only one byte -- the caller is
 * responsible for attaching the address bytes. However, we preallocate them in
 * order to go easy on allocb().
 */

static int
xmit3 (MoatStream state, char cmd, uchar_t what)
{
	mblk_t *mb;
	int err;

	if (state->debug & 0x80)
		printf ("%sX%d%c%x ", KERN_DEBUG,state->debugnr, cmd ? 'c' : 'r', what);
	mb = allocb (state->offset + 1, BPRI_HI);
	if (mb == NULL) {
		if(state->debug & 0x01)
			printf("%sNX4 NoMem ",KERN_WARNING);
		return -ENOENT;
	}
	mb->b_rptr += state->offset;
	mb->b_wptr += state->offset;
	*mb->b_wptr++ = what;
	if ((err = (*state->send) (state->ref, cmd, mb)) != 0)
		freemsg (mb);
	return err;
}

/*
 * Send 4-byte header. Actually enqueue only two bytes -- the caller is
 * responsible for attaching the address bytes.
 */
static int
xmit4 (MoatStream state, char cmd, uchar_t what1, uchar_t what2)
{
	mblk_t *mb;
	int err;

	if (state->debug & 0x80)
		printf ("%sX%d%c%x.%x ", KERN_DEBUG,state->debugnr, cmd ? 'c' : 'r', what1, what2);
	mb = allocb (state->offset + 2, BPRI_HI);
	if (mb == NULL) {
		if(state->debug & 0x01)
			printf("%sNX4 NoMem ",KERN_WARNING);
		return -ENOENT;
	}
	mb->b_rptr += state->offset;
	mb->b_wptr += state->offset;
	*mb->b_wptr++ = what1;
	*mb->b_wptr++ = what2;
	if ((err = (*state->send) (state->ref, cmd, mb)) != 0)
		freemsg (mb);
	return err;
}

#define establish(s) Xestablish(s,__LINE__)
/*
 * Connection established.
 */
static int
Xestablish (MoatStream state, int line)
{
	int err, err2;

	if (state->debug & 0x10)
		printf ("%sEstablish%d %d\n", KERN_EMERG,state->debugnr, line);
	if(state->broadcast) {
		return -ENXIO;
	}
	err = clr_except (state);
	state->RC = 0;
	x75_setstate(state, S_await_up);
	if((state->errors += 10) >= 100) {
		x75_setstate(state, S_down);
		printf("%sERR_G 1, %d\n",KERN_INFO,state->errors);
		state->errors = 0;
		msg_up (state, MDL_ERROR_IND, ERR_G);
		msg_up (state, DL_RELEASE_IND, 0);
		x75_setstate(state, S_down);
		return -ETIMEDOUT;
	}
	err2 = xmit3 (state, 1, L2_SABM | L2_PF_U);
	if (err == 0)
		err = err2;
	restart_T (1, err2);
	if (err == 0)
		err = err2;
	stop_T (3, err2);
	if (err == 0)
		err = err2;
	return err;
}

#define recover_NR(s) Xrecover_NR(s,__LINE__)
/*
 * Reestablish the connection due to lost N_R synchronisation.
 */
static int
Xrecover_NR (MoatStream state, int line)
{
	int err;

	if (state->flush != NULL)
		(*state->flush) (state->ref);
	printf("%sERR_J 1\n",KERN_INFO);
	msg_up (state, MDL_ERROR_IND, ERR_J);
	err = Xestablish (state, line);
	state->L3_req = 0;
	return err;
}

/*
 * Force sending an enquiry packet (P bit set)
 */
static int
enquiry (MoatStream state)
{
	int err, err2;

	err = xmit3 (state, 1, ((state->sentRR = (state->canrecv == NULL || (*state->canrecv) (state->ref))) ? L2_RR : L2_RNR) | (state->v_r << 5) | L2_PF);
	if(err == 0)
		state->ack_pend = 0;
	start_T (1, err2);
	if (err == 0)
		err = err2;
	return err;
}

/*
 * Respond to an enquiry packet (F bit set)
 */
static int
enq_resp (MoatStream state)
{
	int err;

	err = xmit3 (state, 0, ((state->sentRR = (state->canrecv == NULL || (*state->canrecv) (state->ref))) ? L2_RR : L2_RNR) | (state->v_r << 5) | L2_PF);
	if(err == 0)
		state->ack_pend = 0;
	return err;
}

/*
 * T1 (T201) resends packets because no ack has arrived for them.
 */
static void
x75_T1 (MoatStream state)
{
	int err2 = 0;

	state->T1 = 0;
	if (state->debug & 0x10)
		printf ("%sT%d.1 %d RC %d\n", KERN_DEBUG,state->debugnr, state->status, state->RC);
	switch (state->status) {
	case S_await_up:
		if (state->RC != 0) { /* temporary kludge */
			if (state->RC < state->N1) {
				state->RC++;

				printf("%sXtimeout %ld\n",KERN_DEBUG,jiffies);
				err2 = xmit3 (state, 1, (L2_SABM | L2_PF_U);
				if (err2 == -EAGAIN)
					state->RC--;
				start_T (1, err2);
			} else {
				flush_I (state);
				printf("%sERR_G 2, %d\n",KERN_INFO,state->N1);
				msg_up (state, MDL_ERROR_IND, ERR_G);
				msg_up (state, DL_RELEASE_IND, 0);
				x75_setstate(state, S_down);
			}
		} else {
			state->RC = 1;
			start_T (1, err2);
			break;
		}
		break;
	case S_up:
		/*
		 * Implementation decision time. Retransmit the last frame? We choose
		 * not to because we are unable to clear the xmit queue.
		 */
		state->RC = 1;
		enquiry (state);
		start_T (1, err2);
		x75_setstate(state, S_recover);
		break;
	case S_await_down:
		if (state->RC < state->N1) {
			state->RC++;
			xmit3 (state, 1, L2_DISC | L2_PF_U);
			start_T (1, err2);
		} else {
			printf("%sERR_H 1\n",KERN_INFO);
			msg_up (state, MDL_ERROR_IND, ERR_H);
			msg_up (state, DL_RELEASE_CONF, 0);
			x75_setstate(state, S_down);
		}
		break;
	case S_recover:
		if (state->RC < state->N1) {
			enquiry (state);
			state->RC++;
			start_T (1, err2);
		} else {
			printf("%sERR_I 1 %d\n",KERN_INFO,state->RC);
			msg_up (state, MDL_ERROR_IND, ERR_I);
			establish (state);
			state->L3_req = 0;
		}
		break;
	default:;
	}
	x75_check_pending (state, 0);
	return;
}

/*
 * T3/T203 periodically sends an enquiry to make sure that the connection is
 * still alive.
 */
static void
x75_T3 (MoatStream state)
{
	state->T3 = 0;
	if (state->debug & 0x10)
		printf ("%sT%d.3 %d\n", KERN_DEBUG,state->debugnr, state->status);
	switch (state->status) {
	case S_up:
		x75_setstate(state, S_recover);
		(void) enquiry (state);	  /* Errors are handled by retransmission
								   * through T1 */
		state->RC = 0;
		break;
	default:;
	}
	return;
}

/*
 * "OOPS" time. The other side sent a bad frame.
 * 
 * There are some differences between X.25, X.75 and Q.921 in this area,
 * but given a conforming implementation on the other side this code
 * should not be executed anyway. (Yeah, right...)
 */
static int
send_FRMR (MoatStream state, uchar_t pf, uchar_t cntl1, uchar_t cntl2, uchar_t cmd, uchar_t w, uchar_t x, uchar_t y, uchar_t z)
{
	int err = 0;
	mblk_t *mb = allocb (state->offset + 4, BPRI_HI);

	if (mb == NULL)
		return -ENOMEM;
	mb->b_rptr += state->offset;
	mb->b_wptr += state->offset;
	*mb->b_wptr++ = L2_FRMR | (pf ? L2_PF : 0);
	*mb->b_wptr++ = cntl1;
	*mb->b_wptr++ = (state->v_r << 5) | (cmd ? 0x10 : 0) | (state->v_s << 1);
	*mb->b_wptr++ = (w ? 1 : 0) | (x ? 2 : 0) | (y ? 4 : 0) | (z ? 8 : 0);
	if ((err = (*state->send) (state->ref, 0, mb)) != 0)
		freemsg (mb);
	return err;
}

/*
 * Send pending frames.
 */
#ifdef CONFIG_DEBUG_ISDN
int
deb_x75_check_pending (const char *deb_file, unsigned int deb_line, MoatStream state, char fromLow)
#else
int
x75_check_pending (MoatStream state, char fromLow)
#endif
{
	mblk_t *mb, *mb2;
	char did = 0;
	int k_now;
	int err = 0, err2;

#if 0 /* def CONFIG_DEBUG_ISDN */
	if(state->debug & 1)
		printf("%sCP%d %s:%d  ",KERN_DEBUG,state->debugnr,deb_file,deb_line);
#ifdef CONFIG_DEBUG_STREAMS
	cS_check(deb_file,deb_line,&state->UI,NULL);
#endif
#else
	if(state->debug & 1)
		printf("%sCP%d ",KERN_DEBUG,state->debugnr);
#endif

	if(state->status == S_free)
		return -ENXIO;

	while (state->UI.first != NULL && (state->cansend == NULL || (*state->cansend) (state->ref))) {
		mb2 = S_dequeue (&state->UI);
		if(mb2 == NULL)
			break;
		if( /* XXX */ 0 || DATA_REFS(mb2) > 1 || DATA_START(mb2) > mb2->b_rptr - 1) {
			mb = allocb (state->offset + 1, BPRI_MED);
			if (mb == NULL)
				break;
			mb->b_rptr += state->offset + 1;
			mb->b_wptr += state->offset + 1;
			linkb (mb, mb2);
		} else
			mb = mb2;
		*--mb->b_rptr = L2_UI;
		if (state->debug & 1)
			printf ("%sX%dc%x ", KERN_DEBUG,state->debugnr, mb->b_wptr[-1] & 0xFF);
		if ((err = (*state->send) (state->ref, state->asBroadcast ? 3 : 1, mb)) != 0) {
			if (err == -EAGAIN) { /* Undo the above */
				mb->b_rptr++;
				mb = pullupm(mb,1);
				S_requeue (&state->UI, mb);
			} else
				freemsg (mb);
			return 0;
		} else
		did ++;
	}
	/*
	 * If no connection established, bail out now. If recovering, don't try to
	 * send pending I frames because we're still waiting for an ack.
	 */
	if (state->status != S_up) {
		if((state->I.first != NULL) && state->debug)
			printf("%sx75.%d: State %d/%s, pending\n",KERN_DEBUG,state->debugnr,state->status,x75_sname[state->status]);
		if ((state->status == S_await_up) && fromLow) {
			stop_T(1,err);
			x75_T1(state);
		}
		if (state->status != S_recover) {
			if(did && state->backenable)
				(*state->backenable) (state->ref);
			return -EAGAIN;
		}
	} else {
		did=0;
		/*
		 * Send frames until queue full or max # of outstanding frames reached.
		 */
		k_now = (state->v_s - state->v_a) & 0x07;
		/* k_now: Number of sent but unack'd frames. */
		while (k_now < state->k && !state->RNR && (state->cansend == NULL || (*state->cansend) (state->ref))) {
			mb2 = S_nr (&state->I, k_now);
			if (mb2 == NULL)  /* No more work in queue */
				break;
			if( /* XXX */ 0 || DATA_REFS(mb2) > 2 || DATA_START(mb2) > mb2->b_rptr - 1) {
				int off = state->offset + 1;
				mb = allocb (off, BPRI_HI);
				if (mb == NULL)
					break;
				mb->b_rptr += off;
				mb->b_wptr += off;
				linkb(mb,mb2);
			} else {
				mb = mb2;
			}
			*--mb->b_rptr = (state->v_s << 1) | (state->v_r << 5);
			if (state->debug & 1)
				printf ("%sX%dc%x ", KERN_DEBUG,state->debugnr, mb->b_rptr[0] & 0xFF);
			state->v_s = (state->v_s + 1) & 0x07;
			if ((err = (*state->send) (state->ref, 1, mb)) != 0) {
				freemsg (mb);
				break;
			}
			k_now++;
			did++;
		}
		/* Start T1 if we're now waiting for an ack. */
		if (did && !state->T1) {
			stop_T (3, err);
			start_T (1, err);
		}
	}
	/*
	 * Send an ack packet if we didn't do it implicitly with a data frame,
	 * above.
	 * 
	 * TODO: Delay the ack if we can determine that an immediate ack is
	 * not needed, i.e. if the line delay is lower than (k-1) times the
	 * average(?) frame length.
	 */
	if (!state->sentRR) {
		if (state->canrecv == NULL || (*state->canrecv) (state->ref)) {
			state->sentRR = 1;
			did = 0;
			state->ack_pend = 1;		/* Send RR now. This makes sure the if statement, below, fires. */
		}
	} else {
		if (state->canrecv != NULL && !(*state->canrecv) (state->ref))
			state->sentRR = 0;
	}
	if (!did && state->ack_pend) {
		err2 = xmit3 (state, 0, (state->sentRR ? L2_RR : L2_RNR) | (state->v_r << 5));
		if(err2 == 0)
			state->ack_pend = 0;
		if (err == 0)
			err = err2;
	}
#if 0 /* def CONFIG_DEBUG_ISDN */
	else if(did) printf("%sNX send ",KERN_DEBUG );
	else printf("%sNX NoAckPend ",KERN_DEBUG );
#endif
	/*
	 * Ugly Hack time. Continuously ask the remote side what's going on while
	 * it is on RNR. This is for the benefit of partners who forget to send RR
	 * when they can accept data again.
	 */
	if (state->RNR && state->poll && state->trypoll) {
		err2 = xmit3 (state, 1, (state->sentRR ? L2_RR : L2_RNR) | (state->v_r << 5) | L2_PF);
		if(err2 == 0) state->ack_pend = 0;
		if (err == 0)
			err = err2;
	}
	if (state->trypoll)
		state->trypoll = 0;
	return err;
}

/*
 * Check if the received N_R is reasonable, i.e. between v_a and v_s.
 */
static int
checkV (MoatStream state, uchar_t n_r)
{
	if ((n_r == state->v_a) && (n_r == state->v_s))
		return 1;
	if (state->debug & 0x08)
		printf ("%sChk%d %d <= %d <= %d\n",KERN_DEBUG,state->debugnr, state->v_a, n_r, state->v_s);
	if (state->v_a <= state->v_s) {
		if (state->v_a <= n_r && n_r <= state->v_s)
			return 1;
	} else {
		if (state->v_a <= n_r || n_r <= state->v_s)
			return 1;
	}
	printf ("\n%s*** MoatStream-%d Sequence error: V_A %d, N_R %d, V_S %d\n",KERN_WARNING,
			state->debugnr, state->v_a, n_r, state->v_s);
	return 0;
}

/*
 * Deallocate acknowledged frames.
 */
static int
pull_up (MoatStream state, uchar_t n_r)
{
	int ms;
	char didsome = (state->v_a != n_r);

	if (!didsome)
		return 0;
	while (state->v_a != n_r && state->v_a != state->v_s &&
			state->I.first != NULL) {
		freemsg (S_dequeue (&state->I));
		if(state->errors > 0)
			--state->errors;
		state->v_a = (state->v_a + 1) & 0x07;
	}
	if (state->v_a != n_r) {
		printf ("%sx75.%d consistency problem: v_a %d, n_r %d, v_s %d, nblk %d, firstblk %p\n",KERN_WARNING,
				state->debugnr, state->v_a, n_r, state->v_s, state->I.nblocks, state->I.first);
		return -EFAULT;
	}
	if (didsome && state->backenable)
		(*state->backenable) (state->ref);
	return 0;
}


/*
 * Process incoming frames.
 * 
 * This one's a biggie. Annex B of Q.921 is very helpful if you try to wade
 * through it all. Turning optimization on (having a compiler with a correct
 * optimizer may be necessary...) is a good way to make sure that the kernel
 * likes this code.
 *
 * This code went through GNU indent, which unfortunately doubled its
 * line count... Sometimes, life sucks. ;-)
 */
int
x75_recv (MoatStream state, char cmd, mblk_t * mb)
{
	uchar_t x1, x2 = 0;
	char pf = 0;
	int err = 0, err2;
	char isbroadcast = (cmd & 2);

	cmd &= 1;

	/*
	 * Currently, this code never returns anything other than zero because it
	 * always deallocates the incoming frame, which is because we always mess
	 * around with it. This may or may not be a good idea. I don't like special
	 * code for the first two or three bytes being continuous. Besides, in most
	 * cases the caller deallocates anyway if there is an error.
	 */
	if((mb = pullupm (mb, 0)) == NULL)
		return 0;

	x1 = *mb->b_rptr++;
	if (state->debug & 0x80) {
		printf ("%sR%d%c%x ",KERN_DEBUG, state->debugnr, cmd ? 'c' : 'r', x1);
	}
	mb = pullupm(mb,0);
	if ((x1 & L2_m_I) == L2_is_I) {		/* I frame */
		uchar_t n_r, n_s;

		if (isbroadcast) {		  /* Can't broadcast I frames! */
			if (mb != NULL)
				freemsg (mb);
			return /* EINVAL */ 0;
		}
		/* Extract N_R, N_S, P/F. */
		pf = x1 & L2_PF;
		x2 = 0;
		n_s = (x1 >> 1) & 0x07;
		n_r = (x1 >> 5) & 0x07;
		if (!cmd || mb == NULL) {
			err2 = send_FRMR (state, pf, x1, x2, cmd, 1, 1, 0, 0);
			if (err == 0)
				err = err2;
			if (!cmd) {			  /* we shall process empty I frames. */
				if (mb)
					freemsg (mb);
				return /* err */ 0;
			}
		}
		switch (state->status) {
		case S_up:
			if ((state->sentRR = (state->canrecv == NULL || (*state->canrecv) (state->ref)))) {
					/* Room for the packet upstreams? */
				if (mb != NULL && n_s == state->v_r) {
					if ((err2 = (*state->recv) (state->ref, 0, mb)) != 0) {
						/* Hmmm... Assume I'm not ready after all. */
						if (err == 0)
							err = err2;
						goto dropit;	/* This is ugly, but easiest. */
					} else {
						state->v_r = (state->v_r + 1) & 0x07;
						if(state->errors > 0)
							--state->errors;
						mb = NULL;/* Accepted, so forget about it here. */
					}
					state->inREJ = 0;
					if (pf) {	  /* Want immediate Ack. */
						err2 = xmit3 (state, 0, L2_RR | (state->v_r << 5) | L2_PF);
						if(err2 == 0)
							state->ack_pend = 0;
						if (err == 0)
							err = err2;
					} else {	  /* Remember that we have to ack this. */
						state->ack_pend = 1;
					}
				} else {		  /* Duplicate or early packet? Tell the other
								   * side to resync. */
					if (mb != NULL) {
						freemsg (mb);
						mb = NULL;
					}
					if (state->inREJ) {	/* Don't send more than one REJ; that
										 * would upset the protocol. */
						if (pf) {
							err2 = xmit3 (state, 0, L2_RR | (state->v_r << 5) | L2_PF);
							if(err2 == 0)
								state->ack_pend = 0;
							if (err == 0)
								err = err2;
						}
					} else {	  /* Send REJ. */
						state->inREJ = 1;
						err2 = xmit3 (state, 0, L2_REJ | (state->v_r << 5) | (pf ? L2_PF : 0));
						if(err2 == 0)
							state->ack_pend = 0;
						if (err == 0)
							err = err2;
					}
				}
			} else {			  /* Packet not acceptable. Tell them that we
								   * are busy (or something). */
			  dropit:
				freemsg (mb);
				mb = NULL;
				if (pf) {
					err2 = xmit3 (state, 0, L2_RNR | (state->v_r << 5) | L2_PF);
					if(err2 == 0)
						state->ack_pend = 0;
					if (err == 0)
						err = err2;
				}
			}
			if (checkV (state, n_r)) {	/* Packet in range */
				if (state->RNR) { /* other side not ready */
					err2 = pull_up (state, n_r);
					if (err == 0)
						err = err2;
				} else {
					if (n_r == state->v_s) {	/* Everything ack'd */
						err2 = pull_up (state, n_r);
						if (err == 0)
							err = err2;
						stop_T (1, err2);
						if (err == 0)
							err = err2;
						restart_T (3, err2);
						if (err == 0)
							err = err2;
					} else {
						if (n_r != state->v_a) {		/* Something ack'd */
							err2 = pull_up (state, n_r);
							if (err == 0)
								err = err2;
							restart_T (1, err2);
							if (err == 0)
								err = err2;
						}
						/* Else if nothing ack'd, do nothing. */
					}
				}
			} else {			  /* Uh oh. The packet is either totally out of
								   * it, or packets got reordered. Both cases
								   * are seriously bad. */
				err2 = recover_NR (state);
				if (err == 0)
					err = err2;
			}
			break;
		default:;
		}
		/* I frames in other states get dropped */
	} else if ((x1 & L2_m_SU) == L2_is_S) {		/* S frame */
		uchar_t n_r;
		uchar_t code;

		if (isbroadcast) {		  /* No broadcast S frames allowed either. */
			if (mb != NULL)
				freemsg (mb);
			return /* EINVAL */ 0;
		}
		x2 = 0;
		n_r = (x1 >> 5) & 0x07;
		code = x1 & 0x0F;
		pf = x1 & L2_PF;
		mb = pullupm (mb, 0);
		if (mb != NULL) {		  /* An S Frame with data field? Huh?? */
			err2 = send_FRMR (state, pf, x1, x2, cmd, 1, 1, 0, 0);
			if (err == 0)
				err = err2;
			freemsg (mb);
			return /* err */ 0;
		}
		switch (code) {
		case L2_RR:
			state->trypoll = 0;
			switch (state->status) {
			case S_up:
				if (cmd) {
					if (pf) {
						err2 = enq_resp (state);
						if (err == 0)
							err = err2;
					}
				} else {
					if (pf) {	  /* This should only happen while in the
								   * S_recover state ... or when doing the
								   * force-poll-while-RNR hack. Yes it _is_
								   * ugly. I know that. */
						if (!(state->RNR && state->poll)) {
							printf("%sERR_A 1, RNR %d poll %d\n",KERN_INFO,state->RNR,state->poll);
							err2 = msg_up (state, MDL_ERROR_IND, ERR_A);
							if (err == 0)
								err = err2;
						}
					}
				}
				state->RNR = 0;
				if (checkV (state, n_r)) {
					if (n_r == state->v_s) {
						err2 = pull_up (state, n_r);
						if (err == 0)
							err = err2;
						stop_T (1, err2);
						if (err == 0)
							err = err2;
						restart_T (3, err2);
						if (err == 0)
							err = err2;
					} else {
						if (n_r != state->v_a) {
							err2 = pull_up (state, n_r);
							if (err == 0)
								err = err2;
							restart_T (1, err2);
							if (err == 0)
								err = err2;
						}
					}
				} else {
					err2 = recover_NR (state);
					if (err == 0)
						err = err2;
				}
				break;
			case S_recover:
				state->RNR = 0;
				if (cmd) {
					if (pf) {
						err2 = enq_resp (state);
						if (err == 0)
							err = err2;
					}
					if (checkV (state, n_r)) {
						err2 = pull_up (state, n_r);
						if (err == 0)
							err = err2;
					} else {
						err2 = recover_NR (state);
						if (err == 0)
							err = err2;
					}
				} else {
					if (pf) {
						if (checkV (state, n_r)) {
							err2 = pull_up (state, n_r);
							if (err == 0)
								err = err2;
							stop_T (1, err2);
							if (err == 0)
								err = err2;
							start_T (3, err2);
							if (err == 0)
								err = err2;
							err2 = retransmit (state);
							if (err == 0)
								err = err2;
							x75_setstate(state, S_up);
						} else {
							err2 = recover_NR (state);
							if (err == 0)
								err = err2;
						}
					} else {
						if (checkV (state, n_r)) {
							err2 = pull_up (state, n_r);
							if (err == 0)
								err = err2;
						} else {
							err2 = recover_NR (state);
							if (err == 0)
								err = err2;
						}
					}
				}
				break;
			default:;
			}
			break;
		case L2_RNR:
			state->trypoll = !pf;
			switch (state->status) {
			case S_up:
				if (cmd) {
					if (pf) {
						err2 = enq_resp (state);
						if (err == 0)
							err = err2;
					}
				} else {
					if (pf) {
						if (!(state->poll && state->RNR)) {
							printf("%sERR_A 2\n",KERN_INFO );
							err2 = msg_up (state, MDL_ERROR_IND, ERR_A);
							if (err == 0)
								err = err2;
						}
					}
				}
				state->RNR = 1;
				if (checkV (state, n_r)) {
					err2 = pull_up (state, n_r);
					if (err == 0)
						err = err2;
					stop_T (1, err2);
					if (err == 0)
						err = err2;
					restart_T (3, err2);
					if (err == 0)
						err = err2;
				} else {
					err2 = recover_NR (state);
					if (err == 0)
						err = err2;
				}
				break;
			case S_recover:
				state->RNR = 1;
				if (cmd) {
					if (pf) {
						err2 = enq_resp (state);
						if (err == 0)
							err = err2;
					}
					if (checkV (state, n_r)) {
						err2 = pull_up (state, n_r);
						if (err == 0)
							err = err2;
					} else {
						err2 = recover_NR (state);
						if (err == 0)
							err = err2;
					}
				} else {
					if (pf) {
						if (checkV (state, n_r)) {
							err2 = pull_up (state, n_r);
							if (err == 0)
								err = err2;
							stop_T (1, err2);
							if (err == 0)
								err = err2;
							start_T (3, err2);
							if (err == 0)
								err = err2;
							err2 = retransmit (state);
							if (err == 0)
								err = err2;
							x75_setstate(state, S_up);
						} else {
							err2 = recover_NR (state);
							if (err == 0)
								err = err2;
						}
					} else {
						if (checkV (state, n_r)) {
							err2 = pull_up (state, n_r);
							if (err == 0)
								err = err2;
						} else {
							err2 = recover_NR (state);
							if (err == 0)
								err = err2;
						}
					}
				}
				break;
			default:;
			}
			break;
		case L2_REJ:
			state->trypoll = 0;
			switch (state->status) {
			case S_up:
				if (cmd) {
					if (pf) {
						err2 = enq_resp (state);
						if (err == 0)
							err = err2;
					}
				} else {
					if (pf) {
						if (!(state->poll && state->RNR)) {
							printf("%sERR_A 3\n",KERN_INFO );
							err2 = msg_up (state, MDL_ERROR_IND, ERR_A);
							if (err == 0)
								err = err2;
						}
					}
				}
				state->RNR = 0;
				if (checkV (state, n_r)) {
					err2 = pull_up (state, n_r);
					if (err == 0)
						err = err2;
					stop_T (1, err2);
					if (err == 0)
						err = err2;
					start_T (3, err2);
					if (err == 0)
						err = err2;
					err2 = retransmit (state);
					if (err == 0)
						err = err2;
				} else {
					err2 = recover_NR (state);
					if (err == 0)
						err = err2;
				}
				break;
			case S_recover:
				state->RNR = 0;
				if (cmd) {
					if (pf) {
						err2 = enq_resp (state);
						if (err == 0)
							err = err2;
					}
					if (checkV (state, n_r)) {
						err2 = pull_up (state, n_r);
						if (err == 0)
							err = err2;
					} else {
						err2 = recover_NR (state);
						if (err == 0)
							err = err2;
					}
				} else {
					if (pf) {
						if (checkV (state, n_r)) {
							err2 = pull_up (state, n_r);
							if (err == 0)
								err = err2;
							stop_T (1, err2);
							if (err == 0)
								err = err2;
							start_T (3, err2);
							if (err == 0)
								err = err2;
							err2 = retransmit (state);
							if (err == 0)
								err = err2;
							x75_setstate(state, S_up);
						} else {
							err2 = recover_NR (state);
							if (err == 0)
								err = err2;
						}
					} else {
						if (checkV (state, n_r)) {
							err2 = pull_up (state, n_r);
							if (err == 0)
								err = err2;
						} else {
							err2 = recover_NR (state);
							if (err == 0)
								err = err2;
						}
					}
				}
				break;
			default:;
			}
			break;
		default:
			err2 = send_FRMR (state, pf, x1, x2, cmd, 1, 0, 0, 0);
			if (err == 0)
				err = err2;
			printf("%sERR_L 1\n",KERN_INFO);
			err2 = msg_up (state, MDL_ERROR_IND, ERR_L);
			if (err == 0)
				err = err2;
			break;
		}
	} else {					  /* U frame */
		uchar_t code;

		pf = (x1 & L2_PF);
		code = x1 & ~L2_PF;
		if (isbroadcast && (code != L2_UI || !cmd)) {
			if (mb != NULL)
				freemsg (mb);
			return /* EINVAL */ 0;
		}
#define L2__CMD 0x100		  /* Out of range -- makes for a simpler case
							   * statement */
		switch (code | (cmd ? L2__CMD : 0)) {
		case L2_SABM | L2__CMD:
			if (mb != NULL) {
				err2 = send_FRMR (state, pf, x1, 0, cmd, 1, 1, 0, 0);
				if (err == 0)
					err = err2;
				printf("%sERR_N 1\n",KERN_INFO );
				err2 = msg_up (state, MDL_ERROR_IND, ERR_N);
				if (err == 0)
					err = err2;
				break;
			}
			switch (state->status) {
			case S_down:
				if(state->broadcast) {
					err2 = xmit3 (state, 0, L2_DM | (pf ? L2_PF : 0));
					if (err == 0)
						err = err2;
					err2 = clr_except (state);
					if (err == 0)
						err = err2;
				} else {
					err2 = xmit3 (state, 0, L2_UA | (pf ? L2_PF : 0));
					if (err == 0)
						err = err2;
					err2 = clr_except (state);
					if (err == 0)
						err = err2;
					err2 = msg_up (state, DL_ESTABLISH_IND, 0);
					if (err == 0)
						err = err2;
					err2 = flush_I (state);
					if (err == 0)
						err = err2;
					stop_T (1, err2);
					if (err == 0)
						err = err2;
					start_T (3, err2);
					if (err == 0)
						err = err2;
					x75_setstate(state, S_up);
					if(state->backenable)
						(*state->backenable) (state->ref);
				}
				break;
			case S_await_up:
				err2 = xmit3 (state, 0, L2_UA | (pf ? L2_PF : 0));
				if (err == 0)
					err = err2;
				break;
			case S_await_down:
				err2 = xmit3 (state, 0, L2_DM | (pf ? L2_PF : 0));
				if (err == 0)
					err = err2;
				break;
			case S_up:
			case S_recover:
				err2 = xmit3 (state, 0, L2_UA | (pf ? L2_PF : 0));
				if (err == 0)
					err = err2;
				err2 = clr_except (state);
				if (err == 0)
					err = err2;
				printf("%sERR_F 1\n",KERN_INFO );
				err2 = msg_up (state, MDL_ERROR_IND, ERR_F);
				if (err == 0)
					err = err2;
				if (state->v_s != state->v_a) {
					err2 = flush_I (state);
					if (err == 0)
						err = err2;
					err2 = msg_up (state, DL_ESTABLISH_IND, 0);
					if (err == 0)
						err = err2;
				} else {
					err2 = flush_I (state);
					if (err == 0)
						err = err2;
				}
				stop_T (1, err2);
				if (err == 0)
					err = err2;
				start_T (3, err2);
				if (err == 0)
					err = err2;
				x75_setstate(state, S_up);
				break;
			case S_free:;
			}
			break;
		case L2_DISC | L2__CMD:
			if (mb != NULL) {
				err2 = send_FRMR (state, pf, x1, x2, cmd, 1, 1, 0, 0);
				if (err == 0)
					err = err2;
				printf("%sERR_N 2\n",KERN_INFO );
				err2 = msg_up (state, MDL_ERROR_IND, ERR_N);
				if (err == 0)
					err = err2;
				break;
			}
			switch (state->status) {
			case S_down:
			case S_await_down:
				err2 = xmit3 (state, 0, L2_UA | (pf ? L2_PF : 0));
				if (err == 0)
					err = err2;
				break;
			case S_await_up:
				err2 = xmit3 (state, 0, L2_DM | (pf ? L2_PF : 0));
				if (err == 0)
					err = err2;
				break;
			case S_up:
				err2 = flush_I (state);
				if (err == 0)
					err = err2;
				err2 = xmit3 (state, 0, L2_UA | (pf ? L2_PF : 0));
				if (err == 0)
					err = err2;
				err2 = msg_up (state, DL_RELEASE_IND, 0);
				if (err == 0)
					err = err2;
				stop_T (1, err2);
				if (err == 0)
					err = err2;
				stop_T (3, err2);
				if (err == 0)
					err = err2;
				x75_setstate(state, S_down);
				break;
			case S_recover:
				err2 = flush_I (state);
				if (err == 0)
					err = err2;
				err2 = xmit3 (state, 0, L2_UA | (pf ? L2_PF : 0));
				if (err == 0)
					err = err2;
				err2 = msg_up (state, DL_RELEASE_IND, 0);
				if (err == 0)
					err = err2;
				stop_T (1, err2);
				if (err == 0)
					err = err2;
				x75_setstate(state, S_down);
				break;
			case S_free:;
			}
			break;
		case L2_DM:
			if (mb != NULL) {
				err2 = send_FRMR (state, pf, x1, x2, cmd, 1, 1, 0, 0);
				if (err == 0)
					err = err2;
				printf("%sERR_N 3\n",KERN_INFO );
				err2 = msg_up (state, MDL_ERROR_IND, ERR_N);
				if (err == 0)
					err = err2;
				break;
			}
			switch (state->status) {
			case S_down:
				if (!pf) {
					err2 = establish (state);
					if (err == 0)
						err = err2;
					state->L3_req = 0;
				}
				break;
			case S_await_up:
				if (pf) {
					err2 = flush_I (state);
					if (err == 0)
						err = err2;
					err2 = msg_up (state, DL_RELEASE_IND, 0);
					if (err == 0)
						err = err2;
					stop_T (1, err2);
					if (err == 0)
						err = err2;
					x75_setstate(state, S_down);
				}
				break;
			case S_await_down:
				if (pf) {
					err2 = flush_I (state);
					if (err == 0)
						err = err2;
					err2 = msg_up (state, DL_RELEASE_CONF, 0);
					if (err == 0)
						err = err2;
					stop_T (1, err2);
					if (err == 0)
						err = err2;
					x75_setstate(state, S_down);
				}
				break;
			case S_up:
			case S_recover:
				if (pf) {
					printf("%sERR_B 1\n",KERN_INFO );
					err2 = msg_up (state, MDL_ERROR_IND, ERR_B);
					if (err == 0)
						err = err2;
				} else {
					printf("%sERR_E 1\n",KERN_INFO );
					err2 = msg_up (state, MDL_ERROR_IND, ERR_E);
					if (err == 0)
						err = err2;
					err2 = establish (state);
					if (err == 0)
						err = err2;
					state->L3_req = 0;
				}
				break;
			case S_free:;
			}
			break;
		case L2_UA:
			if (mb != NULL) {
				err2 = send_FRMR (state, pf, x1, x2, cmd, 1, 1, 0, 0);
				if (err == 0)
					err = err2;
				printf("%sERR_N\n",KERN_INFO );
				err2 = msg_up (state, MDL_ERROR_IND, ERR_N);
				if (err == 0)
					err = err2;
				break;
			}
			switch (state->status) {
			case S_up:
			case S_down:
			case S_recover:
				printf("%sERR_CD 1\n",KERN_INFO );
				err2 = msg_up (state, MDL_ERROR_IND, ERR_C | ERR_D);
				if (err == 0)
					err = err2;
				break;
			case S_await_up:
				if (pf) {
					if (state->L3_req) {
						err2 = msg_up (state, DL_ESTABLISH_CONF, 0);
						if (err == 0)
							err = err2;
					} else if (state->v_s != state->v_a) {
						err2 = flush_I (state);
						if (err == 0)
							err = err2;
						err2 = msg_up (state, DL_ESTABLISH_IND, 0);
						if (err == 0)
							err = err2;
					}
					x75_setstate(state, S_up);
					stop_T (1, err2);
					if (err == 0)
						err = err2;
					start_T (3, err2);
					if (err == 0)
						err = err2;
					state->v_r = state->v_s = state->v_a = 0;
					if(state->backenable)
						(*state->backenable) (state->ref);
				} else {
					printf("%sERR_D 1\n",KERN_INFO );
					err2 = msg_up (state, MDL_ERROR_IND, ERR_D);
				}
				if (err == 0)
					err = err2;
				break;
			case S_await_down:
				if (pf) {
					err2 = msg_up (state, DL_RELEASE_CONF, 0);
					if (err == 0)
						err = err2;
					stop_T (1, err2);
					if (err == 0)
						err = err2;
					x75_setstate(state, S_down);
				} else {
					printf("%sERR_D 2\n",KERN_INFO );
					err2 = msg_up (state, MDL_ERROR_IND, ERR_D);
				}
				if (err == 0)
					err = err2;
				break;
			case S_free:;
			}
			break;
		case L2_UI | L2__CMD:
			if (mb == NULL) {	  /* Missing data. */
				if (!isbroadcast) {
					err2 = send_FRMR (state, pf, x1, x2, cmd, 1, 1, 0, 0);
					if (err == 0)
						err = err2;
				}
				break;
			}
			if ((err2 = (*state->recv) (state->ref, isbroadcast ? 3 : 1, mb)) != 0) {
				if (err == 0)
					err = err2;
				freemsg (mb);
			}
			mb = NULL;
			break;
		case L2_XID | L2__CMD:
		case L2_XID:			  /* TODO: Do something about XID frames. */
			break;
		case L2_FRMR:
		case L2_FRMR | L2__CMD:	/* technically an invalid frame, but replying with 
									FRMR here is _bad_ */
			printf("%sERR_D 3\n",KERN_INFO );
			err2 = msg_up (state, MDL_ERROR_IND, ERR_D);
			if (err == 0)
				err = err2;
			if (state->status == S_up || state->status == S_recover) {
				establish (state);
				state->L3_req = 0;
			}
			break;
		default:
			err = -EINVAL;
			err2 = send_FRMR (state, pf, x1, x2, cmd, 1, 0, 0, 0);
			if (err == 0)
				err = err2;
			printf("%sERR_L 2\n",KERN_INFO );
			err2 = msg_up (state, MDL_ERROR_IND, ERR_L);
			if (err == 0)
				err = err2;
			break;
		}
	}
	err2 = x75_check_pending (state, 0);	/* if (err == 0) err = err2; */
	if (mb != NULL)
		freemsg (mb);
	return /* err */ 0;
}

/*
 * Enqueue frame to be sent out.
 * Empty messages are silently discarded.
 */
int
x75_send (MoatStream state, char isUI, mblk_t * mb)
{
	if (msgdsize(mb) <= 0) 
		freemsg(mb);
	else if (isUI)
		S_enqueue (&state->UI, mb);
	else {
		if(state->broadcast)
			return -ENXIO;
		S_enqueue (&state->I, mb);
	}

	state->asBroadcast = (isUI > 1);

	(void) x75_check_pending (state, 0);	/* Send the frame, if possible */
	return 0;
}

/*
 * Test if we can send.
 */
int
x75_cansend (MoatStream state, char isUI)
{
	if(state->cansend != NULL)
		(void)(*state->cansend) (state->ref); /* Trigger bringing L1 up */
	if (isUI)
		return (state->UI.nblocks < 3);		/* arbitrary maximum */
	else						  /* This allows us to enqueue one additional
								   * frame, which is a Good Thing. */
		return (state->I.nblocks <= state->k);
}

/*
 * Test if we can receive.
 */
int
x75_canrecv (MoatStream state)
{
	/* Just ask the upper layer. */
	return (*state->canrecv) (state->ref);
}

/*
 * Take the stream layer up / down.
 */
#ifdef CONFIG_DEBUG_ISDN
int
deb_x75_changestate (const char *deb_file,unsigned int deb_line, MoatStream state, uchar_t ind, char isabort)
#else
int
x75_changestate (MoatStream state, uchar_t ind, char isabort)
#endif
{
	int err = 0, err2 = 0;
	int nonestablish = 1;

#ifdef CONFIG_DEBUG_ISDN
	if(state->debug & 0x10)
	    printf("%sx75.%d: State %d/%s for ind %d %d from %s:%d\n",KERN_DEBUG,state->debugnr,state->status,
			x75_sname[state->status],ind,isabort,deb_file,deb_line);
#else
	if(state->debug & 0x10)
	    printf("%sx75.%d: State %d/%s for ind %d %d\n",KERN_DEBUG,state->debugnr,state->status,
			x75_sname[state->status],ind,isabort);
#endif
	if (isabort)
		goto doabort;
	switch (ind) {
	default:
		err = -ENOENT;
		break;
	case DL_ESTABLISH_CONF:	  /* Force establishment, for situations where
								   * we dont need the initial handshake. This
								   * usually happens because an idiot
								   * implementor doesn't want to implement U
								   * frame handling for automode. */
		if (state->status == S_up || state->status == S_recover)
			break;				  /* Already established. */
		if (state->debug & 0x10)
			printf ("%sX75%d: Forced establish.\n",KERN_DEBUG, state->debugnr);
		 /* flush_I (state); */
		state->errors = 0;
		if (state->status != S_down && state->status != S_free)
			stop_T (1, err2);
		if (err == 0)
			err = err2;
		start_T (3, err2);
		if (err == 0)
			err = err2;
		x75_setstate(state, S_up);
		msg_up (state, DL_ESTABLISH_CONF, 0);
		if(state->backenable)
			(*state->backenable) (state->ref);
		break;
	case DL_ESTABLISH_REQ:
	case DL_ESTABLISH_IND:		  /* Take it up. */
		switch (state->status) {
		case S_down:
		case S_await_down:
			if(ind == DL_ESTABLISH_IND /* && state->UI.first == NULL && state->UI.first == NULL */ ) {
				if(0)printf("%sx75.%d: DL_ESTABLISH_IND, down, nothing done\n",KERN_DEBUG,state->debugnr);
				break;
			}
			err = establish (state);
			nonestablish = 0;
			state->L3_req = 1;
			state->errors = 0;
			break;
		case S_await_up:
			if (ind == DL_ESTABLISH_REQ)
				break;
#if 0 /* Q.921 says to do this, but I can't think of a reason to. */
	/* This flush also breaks top-down on-demand connection setup,
	   i.e. starting up the lower layer automatically if the upper
       layer has some data to deliver. */
			err = flush_I (state);
#endif
			state->L3_req = 1;
			break;
		case S_up:
		case S_recover:		  /* L1 reestablishment */
			if (ind == DL_ESTABLISH_REQ)
				break;
			err = flush_I (state);
			err2 = establish (state);
			nonestablish = 0;
			if (err == 0)
				err = err2;
			state->L3_req = 1;
			break;
		default:;
		}
		break;
	case DL_RELEASE_REQ:		  /* Take it down normally. */
		state->errors = 0;
		switch (state->status) {
		case S_down:
			err = msg_up (state, DL_RELEASE_CONF, 0);
			break;
		case S_up:
			x75_setstate(state, S_await_down);
			err = flush_I (state);
			state->RC = 0;
			err2 = xmit3 (state, 1, L2_DISC | L2_PF_U);
			if (err == 0)
				err = err2;
			stop_T (3, err2);
			if (err == 0)
				err = err2;
			restart_T (1, err2);
			if (err == 0)
				err = err2;
			break;
		case S_recover:
			x75_setstate(state, S_await_down);
			err = flush_I (state);
			state->RC = 0;
			err2 = xmit3 (state, 1, L2_DISC | L2_PF_U);
			if (err == 0)
				err = err2;
			restart_T (1, err2);
			if (err == 0)
				err = err2;
			break;
		default:;
		}
		break;

	case DL_RELEASE_CONF:
	  doabort:					  /* Just disconnect. The other side will
								   * either also realize that L1 is down, or
								   * time out eventually. */
		switch (state->status) {
		case S_await_up:
		case S_down:
		case S_up:
		case S_recover:
			err = kill_me (state, DL_RELEASE_IND);
			break;
		case S_await_down:
			err = kill_me (state, DL_RELEASE_CONF);
			break;
		case S_free:;
		}
		x75_setstate(state, S_down);
	}
	if (err == 0) {
		err2 = x75_check_pending (state, nonestablish);
		if (err == 0)
			err = err2;
	}
	return err;
}

/*
 * Initialize data.
 */
int
x75_initconn (MoatStream state)
{
	bzero (&state->I, sizeof (struct _smallq));
	bzero (&state->UI, sizeof (struct _smallq));

	state->v_a = 0;
	state->v_s = 0;
	state->v_r = 0;
	state->RC = 0;
	state->status = S_down;
	state->L3_req = 0;
	state->RNR = 0;
	state->sentRR = 1;
	state->errors = 0;
	state->ack_pend = 0;
	state->inREJ = 0;
	state->T1 = 0;
	state->T3 = 0;
	if (state->N1 == 0)
		state->N1 = 3;
	if (state->RUN_T1 == 0)
		state->RUN_T1 = 10;
	if (state->RUN_T3 == 0)
		state->RUN_T3 = 100;
	if (state->RUN_T3 < state->RUN_T1 * 2)
		state->RUN_T3 = state->RUN_T1 * 2;
	if (state->send == NULL
			|| state->recv == NULL
			|| state->state == NULL)
		return -EFAULT;
	if(0)printf("%sX75 %d: Init %d %d\n",KERN_DEBUG,state->debugnr,state->RUN_T1,state->RUN_T3);
	return 0;
}


#ifdef MODULE
static int do_init_module(void)
{
	return 0;
}

static int do_exit_module(void)
{
	return 0;
}
#endif
