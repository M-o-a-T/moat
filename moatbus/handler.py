from collections import deque
from moatbus.message import BusMessage
from enum import IntEnum
import inspect

class S(IntEnum):

# states
    # Wait for the bus to go idle. "settle" is ignored.
    ERROR = -1
    WAIT_IDLE = 0

    # Bus is idle.
    IDLE = 1 # "Settle" means that the back-off timer is running
    READ = 2
    READ_ACK = 3
    READ_ACQUIRE = 4
    WRITE = 10
    WRITE_ACQUIRE = 11
    WRITE_ACK = 12 # entered after READ sees the last bit
    WRITE_END = 13 # entered after WRITE_ACK is verified


LEN = [None,None, 7,5,3,3,2] # messages per chunk
BITS = [None,None, 11,14,11,14,11] # messages per header chunk (11 bits)
N_END = [None,None, 3,2,1,1,1] # flips at end

ERR_FATAL = -10 ## marker
ERR_HOLDTIME = -11
ERR_ACQUIRE = -12
ERR_CRC = -13
ERR_BAD_COLLISION = -14
ERR_ACQUIRE_FATAL = -15 # this cannot happen unless the hardware is insane
ERR_NO_CHANGE = -16 # this cannot happen unless the reader code is broken
ERR_ZERO = -17 # no wire is set, which should not happen
ERR_FLAP = -18 # too many changes, too little timeouts

RES_SUCCESS = 0
RES_MISSING = 1
RES_ERROR = 2
RES_FATAL = 3

T_BREAK = 0
T_ZERO = 5
T_ERROR = 10

class BaseHandler:
    """
    This class implements bus message handling.

    You need to override these procedures:

    * set_timeout(dly)   -- call .timeout after dly*self.delay usecs; 0=disable
    * set_wire(bits)     -- set (i.e. pull down) these bits
    * get_wire()         -- return the bits that are currently set (i.e. low)
    * process(msg)       -- this message has arrived, handle it!
    * report_error(typ)  -- a problem has ocurred

    External code will call these methods:
    * send (msg, prio?) -- send a message with priority (or not).
    * wire (bits)       -- update wire state. May be triggered immediately,
                           or sometime later, by .set_wire().
    * timeout()         -- when the timeout runs out
    """

    def __init__(self, wires=3):
        """
        Set up a MoatBus handler using these many bits with this line
        delay.

        The delay is the absolute minimum time to ensure that a signal
        change at A reliably arrives at B, no matter what A and B are.
        Delays shorter than that make no sense.
        """
        self.WIRES = wires
        self.MAX = (1<<wires)-1
        self.LEN = LEN[wires]
        self.BITS = BITS[wires]
        self.N_END = N_END[wires]
        self.VAL_END = self.MAX ** self.N_END -1
        self.VAL_MAX = (1<<self.BITS) -1

        self.last = self.current = self.get_wire()
        self.settle = False

        self._q = deque()
        self._prio_q = deque()
        self.sending = None
        self.sending_q = None
        self.want_prio = None

        self.backoff = None
        self.no_backoff = False
        self.retries = None

        self.last_zero = None if self.current else 0
        # set this to zero when .current is zeroed, None when .current is set to something else.
        # If not None, increment by the timer value whenever we set a timer.
        # When entering Idle, use a defined total time from IDLE_WAIT to IDLE (settle=True).
        # Writing may start on IDLE(settle=False) which is the time that depends on back-off and whatnot.
        self.flapping = 0

        self.state = S.WAIT_IDLE
        self.reset()
        self._set_timeout(T_ZERO)

    def report_error(self, typ, **kw):
        """
        OVERRIDE: There's been a comm problem.
        """
        raise RuntimeError("Override me")

    def debug(self, msg, *a):
        """
        OVERRIDE: Debug me!
        """
        pass

    def set_timeout(self, timeout):
        """
        OVERRIDE: Arrange to call .timeout after @timeout usecs. <0=off,
        zero=Timer B, anything else: Timer A.
        """
        raise RuntimeError("Override me")
    
    def set_wire(self, bits):
        """
        OVERRIDE: Pull down these bits.
        """
        raise RuntimeError("Override me")
    
    def get_wire(self):
        """
        OVERRIDE: Get the current wire state (pulled-low bits).
        """
        raise RuntimeError("Override me")
    
    def process(self, msg):
        """
        OVERRIDE: Process this message.
        Return True if it was for us and thus should be ACKd.
        """
        raise RuntimeError("Override me")
    
    def transmitted(self, msg, res):
        """
        OVERRIDE: This message has been transmitted.
        @res is 0/1/2/-1 for OK/missed/error/fatal.
        """
        raise RuntimeError("Override me")
    
    ########################################

    def send(self, msg, prio=0):
        """
        Queue this message for sending.
        """
        q = self._prio_q if prio else self._q
        q.append(msg)

        self.send_next()
        # all other states: do nothing.
        
    def wire(self, bits):
        """
        Process wire changes.
        """
        while True:
            self.last_zero = None if bits else 0
            if self.state > S.IDLE:
                self.flapping += 1
                if self.flapping > 2*self.WIRES:
                    self.error(ERR_FLAP)
                    return
            self.current = bits
            if self.settle:
                self.debug("Change (Settle) %s",self.state)
                self.wire_settle(bits)
            else:
                self.debug("Change (Delay) %s",self.state)
                self.next_step(False)

            bits = self.get_wire()
            if bits == self.current:
                break

        if self.state > S.IDLE:
            self.settle = True
            self._set_timeout(1)

    def wire_settle(self, bits):
        """
        The wire state has changed: now these bits are pulled low.
        """
        self.debug("WS %02x",bits)

        assert self.state >= S.IDLE

        if self.state == S.IDLE:
            assert bits
            if self.no_backoff and self.sending:
                self.start_writer()
            else:
                self.start_reader(True)

        elif self.state == S.WRITE_ACQUIRE:
            if bits &~ (self.want_prio | (self.want_prio-1)):
                self.debug("PRIO FAIL %02x %02x",bits,self.want_prio)
                self.start_reader(True)

        elif self.state == S.WRITE_ACK:
            if bits & ~(self.ack_masks | self.last):
                self.error(ERR_BAD_COLLISION)

        elif self.state >= S.WRITE:
            if bits & ~(self.intended | self.last):
                self.write_collision(bits & ~(self.intended | self.last), False)

    def _set_timeout(self, val):
        """
        Set a timeout.

        If the line is off, add to last_zero so that we can be accurate
        about WAIT_IDLE.
        """
        if val < 0:
            self.set_timeout(0)
            return
        if val == T_ZERO and self.last_zero is not None:
            val = max(T_ZERO-self.last_zero, 1)
        if self.last_zero is not None and self.last_zero < T_ZERO:
            self.last_zero += val
        self.set_timeout(val)

    def _transmitted(self, msg, res):
        self.transmitted(msg, res)
        self.retries = None
        self.backoff /= 2

    def timeout(self):
        """
        The timeout has arrived.

        If the bus has settled, we read the state and act on it. Otherwise
        the time for the next step has arrived.
        """
        if self.settle:
            self.settle = False
            self.debug("Change Done timer %s",self.state)
            self.timeout_settle()
            self.last = self.current
            if self.state >= S.WRITE:
                self._set_timeout(0)
            elif self.state > S.IDLE:
                self._set_timeout(T_ZERO)
        elif self.settle is False:
            self.debug("Delay Timer %s",self.state)
            self.next_step(True)
            if self.state > S.IDLE:
                self.settle = True
                self._set_timeout(1)
        else:
            # hard timeout
            self.error(ERR_NO_CHANGE)

    def timeout_settle(self):
        """
        State machine: we waited long enough for nothing to happen
        """
        bits = self.current
        self.flapping = 0

        if self.state == S.IDLE:
            # Bus was idle long enough. Start writing?
            if self.sending:
                self.settle = True # correct because .settle means something different in IDLE
                self.start_writer()

        elif self.state == S.WRITE_ACQUIRE:
            if bits == self.want_prio:
                self.set_state(S.WRITE)
            else:
                self.error(ERR_ACQUIRE_FATAL)

        elif self.state == S.READ_ACQUIRE:
            if bits and not bits&(bits-1):
                self.set_state(S.READ)
            else:
                self.error(ERR_ACQUIRE_FATAL)

        elif self.state == S.READ:
            self.read_next(bits)

        elif self.state == S.READ_ACK:
            msg = self.clear_sending()
            if bits & self.ack_mask:
                self._transmitted(msg, RES_SUCCESS)
            elif bits & self.nack_mask:
                self._transmitted(msg, RES_ERROR)
            elif not bits:
                self.retry(msg, RES_MISSING)
            elif bits & self.ack_masks:
                self.retry(msg, RES_ERROR)
            else:
                self.error(ERR_BAD_COLLISION)
                self.retry(msg, RES_FATAL)
            self.set_state(S.WAIT_IDLE)

        elif self.state == S.WRITE:
            if bits != self.intended:
                self.write_collision(bits &~ self.intended, True)

        elif self.state == S.WRITE_ACK:
            if bits & ~self.ack_masks:
                self.error(ERR_BAD_COLLISION)
            elif bits != self.ack_mask:
                self.error(ERR_BAD_COLLISION)
                self.write_collision(bits &~ self.ack_masks, True)
            else:
                self.set_state(S.WRITE_END)

        elif self.state == S.WRITE_END:
            raise RuntimeError("Cannot happen")

        else:
            raise RuntimeError("Unhandled state in timeout",self.state)

    def retry(self, msg, res):
        self.debug("Retry:%d %s", res, msg)
        if res == RES_MISSING:
            r = 2
        elif res == RES_ERROR:
            r = 4
        else:
            r = 5
        if self.retries is None:
            self.retries = r
        elif self.retries == 0:
            self._transmitted(msg, res)
        else:
            self.retries -= 1
            self._q.appendleft(msg)

    def next_step(self, timeout:bool):
        """
        State machine: something should happen

        If @timeout is set we got here because of an idle timer.
        Otherwise, some wire state changed.
        """
        bits = self.current

        if self.state < S.IDLE:
            if timeout:
                self.error(ERR_HOLDTIME)
            elif self.current:
                self._set_timeout(-1)
            else:
                self._set_timeout(T_ZERO)

        elif self.state == S.IDLE:
            # Bus was idle long enough. Start writing?
            if self.sending:
                self.start_writer()
            elif not timeout:
                self.start_reader(True)

        elif self.state < S.WRITE:
            if timeout:
                self.error(ERR_HOLDTIME)
            # otherwise things are changing, which is what we want

        elif self.state == S.WRITE_ACQUIRE:
            if bits == self.want_prio:
                self.start_writer()
                self.set_state(S.WRITE)
            else:
                # Somebody didn't take their wire down in time
                self.error(ERR_ACQUIRE_FATAL)

        elif self.state == S.WRITE:
            if not self.write_next():
                pass
            elif bits &~ (self.last | self.intended):
                self.write_collision(bits &~ self.intended, False)
            else:
                self.set_wire(self.intended)

        elif self.state == S.WRITE_ACK:
            if bits &~ (self.last | self.ack_masks):
                self.error(ERR_BAD_COLLISION)
            else:
                self.set_wire(self.ack_mask)

        elif self.state == S.WRITE_END:
            self.set_state(S.WAIT_IDLE)

        else:
            raise RuntimeError("Unhandled state in timeout",self.state)
    ########################################

    def clear_sending(self):
        msg,self.sending = self.sending,None
        self.sending_q = None
        self.want_prio = None
        return msg

    def start_reader(self, need_acquire:bool):
        """
        Start reading.

        If @settled is False we need to time out.
        """
        self.set_state(S.READ_ACQUIRE if need_acquire else S.READ)

    def start_writer(self):
        self.cur_chunk = ()
        self.sending.start_extract()
        self.set_wire(self.want_prio)
        self.set_state(S.WRITE_ACQUIRE)

    def gen_chunk(self):
        assert not self.cur_pos, self.cur_pos
        if len(self.cur_chunk) == self.N_END:
            return
        xv = val = self.sending.extract_chunk(self.BITS)
        if val is None:
            assert self.cur_chunk
            self.cur_pos = n = self.N_END
            res = [self.MAX]*n
        else:
            res = []
            self.cur_pos = n = self.LEN
            while n:
                val,p = divmod(val,self.MAX)
                res.append(p+1)
                n -= 1
        self.cur_chunk = res
        assert not val, val
        return True

    def write_next(self):
        """
        Prepare to write the next piece.
        """
        if not self.cur_pos:
            self.gen_chunk()
        if not self.cur_pos:
            # switch to reading
            self.set_state(S.READ_ACK)
            return False

        p = self.cur_pos -1
        self.cur_pos = p
        res = self.cur_chunk[p]
        assert 0 < res <= self.MAX

        self.intended = self.last ^ res
        return True

    def write_collision(self, bits:int, settled:bool):
        """
        We noticed a collision when writing.

        @bits: those which I don't want to see.
        @settled: is the current value stable?
        """
        self.want_prio = bits & ~(bits-1)
        # this leaves the lowest-numbered bit turned on
        # this means that we separate our prio from the other sender's
        msg = BusMessage()
        msg.start_add()
        off = self.sending.chunk_offset - self.BITS
        if off:
            msg.add_written(self.sending.pull_bits(off))
        self.val = 0
        n = len(self.cur_chunk)
        self.nval = 0
        while n > self.cur_pos+1:
            n -= 1
            self.val = self.val * self.MAX + self.cur_chunk[n]-1
            self.nval += 1

        bits = self.current
        self.set_state(S.READ)
        if settled:
            self.read_next(bits)
        self.no_backoff = True

    def send_next(self):
        prio = False
        if self.sending is None:
            if self._prio_q:
                self.sending = self._prio_q.popleft()
                self.sending_q = self._prio_q
                prio = True
            elif self._q:
                self.sending = self._q.popleft()
                self.sending_q = self._q
        if self.sending is None:
            return
        if self.want_prio is None:
            self.want_prio = 1<<prio

    def read_done(self):
        self.no_backoff = False
        msg_in,self.msg_in = self.msg_in,None
        if not msg_in.check_crc():
            self.report_error(ERR_CRC)
            self.set_ack_mask()
            if not self.nack_mask:
                self.set_state(S.WAIT_IDLE)
                return
            self.ack_mask = self.nack_mask # oh well
            self.set_state(S.WRITE_ACK)
        elif self.process(msg_in):
            self.set_state(S.WRITE_ACK)
        else:
            # The message is not for us
            self.set_state(S.WAIT_IDLE)


    def set_ack_mask(self):
        # This part is somewhat fragile. Cannot be helped.
        bits = self.last if self.settle else self.current

        self.ack_mask = 2 if bits == 1 else 1
        self.nack_mask = (0 if bits else 2) if self.WIRES == 2 else 4 if bits == 3 or bits == 1 else 2
        self.ack_masks = self.ack_mask | self.nack_mask
        self.debug("AckBits %02x / %02x due to %02x/%d", self.ack_mask,self.nack_mask,bits,self.settle)

    def read_next(self, bits):
        lb=self.last
        bits ^= self.last
        #print("BIT",self.addr,bits-1)
        if not bits:
            self.error(ERR_NO_CHANGE)
            return

        self.no_backoff = False

        self.val = self.val * self.MAX + bits-1
        self.nval += 1
        if self.nval == self.N_END and self.val == self.VAL_END:
            self.read_done()
        elif self.nval == self.LEN:
            if self.val > self.VAL_MAX:
                self.error(ERR_CRC)
            else:
                self.msg_in.add_chunk(self.BITS, self.val)
                self.nval = 0
                self.val = 0

    def error(self, typ):
        if typ == ERR_HOLDTIME and not self.current:
            if self.state < S.IDLE:
                self.set_state(S.IDLE)
            else:
                self.set_state(S.WAIT_IDLE)
            return

        f=inspect.currentframe()
        self.debug("Error %d @%d %d %d",typ,f.f_back.f_lineno,f.f_back.f_back.f_lineno,f.f_back.f_back.f_back.f_lineno)
        if typ<0:
            if self.backoff < 4:
                self.backoff *= 2
            else:
                self.backoff *= 1.5

        self.report_error(typ)
        self.reset()
        if typ >= ERR_FATAL and self.sending is not None:
            msg = self.clear_sending()
            self._transmitted(msg,RES_FATAL)
            self.set_state(S.WAIT_IDLE)

        elif 0 < typ < ERR_FATAL:
            self.set_state(S.ERROR)
        else:
            self.set_state(S.WAIT_IDLE)



    def reset(self):
        self.intended = None

        self.pos = None
        self.cur_pos = None
        self.cur_chunk = None
        self.ack_mask = None
        self.msg_in = BusMessage()

        self.val = 0
        self.nval = 0
        self.backoff = 16
        self.settle = False

    def set_state(self, state):
        if state == self.state:
            return

        f=inspect.currentframe()
        self.debug("State %s @%d %d %d",state,f.f_back.f_lineno,f.f_back.f_back.f_lineno,f.f_back.f_back.f_back.f_lineno)

        if state < S.WRITE and self.state >= S.WRITE:
            # Drop off writing == do not set any wires
            self.set_wire(0)

        if state in (S.READ_ACK, S.WRITE_ACK):
            self.set_ack_mask()

        if state in (S.READ_ACQUIRE, S.WRITE_ACQUIRE):
            self.no_backoff = False

        if state == S.IDLE:
            # entering IDLE: wait some more
            assert not self.current
            self.state = state
            self.settle = True
            self._set_timeout(1 if self.no_backoff and self.sending else self.backoff)

        elif state < S.IDLE and self.state > S.IDLE:
            # Stop active work. Reset our machinery appropriately.
            self.state = state
            self.reset()
            self.send_next()
            if self.current:
                self._set_timeout(-1)
            elif state == S.ERROR:
                self._set_timeout(T_ERROR)
            else:
                self._set_timeout(T_ZERO)

        else:
            self.state = state

