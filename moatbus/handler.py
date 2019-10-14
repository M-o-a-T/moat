from collections import deque
from moatbus.message import BusMessage
from enum import IntEnum
import inspect
from random import random

LEN = [None,None, 7,5,3,3,2] # messages per chunk
BITS = [None,None, 11,14,11,14,11] # messages per header chunk (11 bits)
N_END = [None,None, 3,2,1,1,1] # flips at end

class S(IntEnum): # states
    # These wait for the bus to go idle. "settle" is ignored.
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

class ERR(IntEnum):
    COLLISION = -2 # will retry
    FATAL = -10 ## marker
    HOLDTIME = -11
    ACQUIRE = -12
    CRC = -13
    BAD_COLLISION = -14
    ACQUIRE_FATAL = -15 # this cannot happen unless the hardware is insane
    NO_CHANGE = -16 # this cannot happen unless the reader code is broken
    ZERO = -17 # no wire is set, which should not happen
    FLAP = -18 # too many changes, too little timeouts

class RES(IntEnum):
    SUCCESS = 0
    MISSING = 1
    ERROR = 2
    FATAL = 3

T_BREAK = 0
T_BACKOFF = 2
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

        # Delay after a packet.
        self.backoff = T_BACKOFF
        # Flag to ignore backoff delay. Set immediately after a collision
        self.no_backoff = False
        # How often to try. Filled by state of first attempt.
        self.tries = None

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
            self.current = bits
            if self.state > S.IDLE:
                self.flapping += 1
                if self.flapping > 2*self.WIRES:
                    self.error(ERR.FLAP)
                    return
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
            if not bits:
                return
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
                self.error(ERR.BAD_COLLISION)

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
            self.set_timeout(-1)
            return
        if val == T_ZERO and self.last_zero is not None:
            val = max(T_ZERO-self.last_zero, 1)
        if self.last_zero is not None and self.last_zero < T_ZERO:
            self.last_zero += val
        self.set_timeout(val)

    def _transmitted(self, msg, res):
        self.transmitted(msg, res)
        self.tries = None
        self.backoff = max(self.backoff/2, T_BACKOFF)

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
            self.error(ERR.NO_CHANGE)

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
                self.error(ERR.ACQUIRE_FATAL)

        elif self.state == S.READ_ACQUIRE:
            if bits and not bits&(bits-1):
                self.set_state(S.READ)
            else:
                self.error(ERR.ACQUIRE_FATAL)

        elif self.state == S.READ:
            self.read_next(bits)

        elif self.state == S.READ_ACK:
            msg = self.clear_sending()
            if bits & self.ack_mask:
                self._transmitted(msg, RES.SUCCESS)
            elif bits & self.nack_mask:
                self._transmitted(msg, RES.ERROR)
            elif not bits:
                self.retry(msg, RES.MISSING)
            elif bits & self.ack_masks:
                self.retry(msg, RES.ERROR)
            else:
                self.error(ERR.BAD_COLLISION)
                self.retry(msg, RES.FATAL)
            self.set_state(S.WAIT_IDLE)

        elif self.state == S.WRITE:
            if bits != self.intended:
                self.write_collision(bits &~ self.intended, True)

        elif self.state == S.WRITE_ACK:
            if bits & ~self.ack_masks:
                self.error(ERR.BAD_COLLISION)
            elif bits != self.ack_mask:
                self.error(ERR.BAD_COLLISION)
                self.write_collision(bits &~ self.ack_masks, True)
            else:
                self.set_state(S.WRITE_END)

        elif self.state == S.WRITE_END:
            raise RuntimeError("Cannot happen")

        else:
            raise RuntimeError("Unhandled state in timeout",self.state)

    def retry(self, msg, res):
        self.debug("Retry:%d %s", res, msg)
        if res == RES.MISSING:
            r = 2
        elif res == RES.ERROR:
            r = 4
        else:
            r = 6
        if self.tries is None:
            self.tries = r-1
        if self.tries == 0:
            self._transmitted(msg, res)
        else:
            self.tries -= 1
            self._q.appendleft(msg)
            self.send_next()


    def next_step(self, timeout:bool):
        """
        State machine: something should happen

        If @timeout is set we got here because of an idle timer.
        Otherwise, some wire state changed.
        """
        bits = self.current

        if self.state < S.IDLE:
            if timeout:
                self.error(ERR.HOLDTIME)
            elif self.current:
                self._set_timeout(-1)
            else:
                self._set_timeout(T_ZERO)

        elif self.state == S.IDLE:
            # Bus was idle long enough. Start writing?
            if self.sending:
                self.start_writer()
            elif bits:
                self.start_reader(True)

        elif self.state < S.WRITE:
            if timeout:
                self.error(ERR.HOLDTIME)
            # otherwise things are changing, which is what we want

        elif self.state == S.WRITE_ACQUIRE:
            if bits == self.want_prio:
                self.start_writer()
                self.set_state(S.WRITE)
            else:
                # Somebody didn't take their wire down in time
                self.error(ERR.ACQUIRE_FATAL)

        elif self.state == S.WRITE:
            if not self.write_next():
                pass
            elif bits &~ (self.last | self.intended):
                self.write_collision(bits &~ self.intended, False)
            else:
                self.set_wire(self.intended)

        elif self.state == S.WRITE_ACK:
            if bits &~ (self.last | self.ack_masks):
                self.error(ERR.BAD_COLLISION)
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
        self.settle = True
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
        self.report_error(ERR.COLLISION, src=self.sending.src, dst=self.sending.dst,prio=self.want_prio,off=self.sending.chunk_offset,pos=self.cur_pos,backoff=int(self.backoff*100)/100)
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
        if self.state == S.IDLE and not self.settle:
            self.start_writer()

    def read_done(self):
        self.no_backoff = False
        msg_in,self.msg_in = self.msg_in,None
        if not msg_in.check_crc():
            self.report_error(ERR.CRC)
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
            self.error(ERR.NO_CHANGE)
            return

        self.no_backoff = False

        self.val = self.val * self.MAX + bits-1
        self.nval += 1
        if self.nval == self.N_END and self.val == self.VAL_END:
            self.read_done()
        elif self.nval == self.LEN:
            if self.val > self.VAL_MAX:
                self.error(ERR.CRC)
            else:
                self.msg_in.add_chunk(self.BITS, self.val)
                self.nval = 0
                self.val = 0

    def error(self, typ):
        if typ == ERR.HOLDTIME and not self.current:
            if self.state < S.IDLE:
                self.set_state(S.IDLE)
            else:
                self.set_state(S.WAIT_IDLE)
            return

        f=inspect.currentframe()
        self.debug("Error %d @%d %d %d",typ,f.f_back.f_lineno,f.f_back.f_back.f_lineno,f.f_back.f_back.f_back.f_lineno)
        if typ<0:
            if self.backoff < 2*T_BACKOFF:
                self.backoff *= 2+2*random()
            else:
                self.backoff *= 1.5

        self.report_error(typ)
        self.reset()
        if typ >= ERR.FATAL and self.sending is not None:
            msg = self.clear_sending()
            self._transmitted(msg,RES.FATAL)
            self.set_state(S.WAIT_IDLE)

        elif 0 < typ < ERR.FATAL:
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

