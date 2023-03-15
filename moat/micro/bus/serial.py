## Code to (de)serialize bus messages

from enum import IntEnum
from typing import Optional
import trio
import sys

from .message import BusMessage
from .crc import CRC16

import logging
logger = logging.getLogger(__name__)


class S(IntEnum):
    IDLE = 0
    INIT = 1
    LEN = 2
    LEN2 = 3
    DATA = 4
    CRC1 = 5
    CRC2 = 6
    DONE = 7
    UTF8 = 8

class ERR(IntEnum):
    OVERFLOW = 1
    LOST = 2
    SPURIOUS = 3
    CRC = 4

class SerBus:
    """
    This is a Sans-IO class that implements interfacing a message to a
    serial line instead of the MoaT bus.

    You need to override these methods:

    * set_timeout(Flag)  -- periodically call .timeout if Flag is True / stop if false
    * process(msg)       -- this message has arrived, handle it!
    * process_ack()      -- a message has been transmitted
    * report_error(typ)  -- a problem has ocurred
    * data_out (bytes)   -- send these data

    External code may call these methods:
    * send (msg)         -- send a message with priority (or not).
    * send_ack ()        -- ack a message
    * char_in (bits)     -- received this character from serial/pipe
    * timeout()          -- when the timer triggers
    """

    prio_data = b"\x01\x02\x81\x82"
    spinner = ["/","-","\\","|"]
    spin_pos = 0

    def __init__(self):
        # incoming
        self.m_in = None # bus message
        self.crc_in = 0
        self.len_in = 0
        self.prio_in = 0

        # outgoing
        self.crc_out = 0

        self.s_in = S.IDLE

        self.idle = 0  # counter, to drop partial messages
        self.alloc_in()

        self.log_buf = b""

    def report_error(self, typ, **kw):
        """
        OVERRIDE: There's been a comm problem.
        """
        raise RuntimeError("Override me")

    def set_timeout(self, flag):
        """
        OVERRIDE: Arrange to periodically call .timeout, or not,
        depending on whether @fag is True, or not.
        """
        raise RuntimeError("Override me")
    
    def process(self, msg):
        """
        OVERRIDE: Process this message.
        """
        raise RuntimeError("Override me")

    def process_ack(self):
        """
        OVERRIDE: Process this incoming ACK.
        """
        raise RuntimeError("Override me")

    def data_out(self, data: bytes):
        """
        OVERRIDE: Send these serial data    
        """
        raise RuntimeError("Override me")

    def alloc_in(self):
        self.m_in = BusMessage()
        self.crc_in = CRC16()
        self.m_in.start_add()

    def send(self, msg):
        """
        Queue a message
        """
        self.data_out(self.send_data(msg))

    def send_ack(self):
        """
        Queue an ACK
        """
        self.data_out(b'\x06')

    def dump_log_buf(self):
        if not self.log_buf:
            return
        try:
            b = self.log_buf.decode("utf-8")
        except Exception:
            b = self.log_buf.decode("latin1")
        if b in {"L1","L2","L3"}:
            print(self.spinner[self.spin_pos],end="\r")
            sys.stdout.flush()
            self.spin_pos = (self.spin_pos+1) % len(self.spinner)
        else:
            logger.debug("R: %s", b);
        self.log_buf = b""

    @staticmethod
    def now():
        return trio.current_time()

    def char_in(self, ci:int):
        """
        process an incoming serial character
        """
        self.idle = 0

        if self.s_in == S.IDLE:
            if ci == 6:
                self.process_ack()
            elif (prio := self.prio_data.find(ci)) > -1:
                self.prio_in = prio
                self.s_in = S.LEN
            elif not (~ci & 0xC0):
                self.s_in = S.UTF8
                self.len_in = 7 - (ci ^ 0xFF).bit_length()
            elif ci not in (10,13):  # CR/LF
                self.log_buf += bytes((ci,))
                self.log_buf_t = self.now()
                return
            elif self.log_buf:
                self.dump_log_buf()

        elif self.s_in == S.UTF8:
            if ci & 0xC0 == 0x80:
                self.len_in -= 1
                if self.len_in:
                    return
            else:
                self.len_in = 0
            self.s_in = S.IDLE

        elif self.s_in == S.LEN:
            self.set_timeout(True)

            if ci & 0x80:
                self.len_in = (ci & 0x7F) << 8
                self.s_in = S.LEN2
            else:
                self.len_in = ci
                self.s_in = S.DATA

        elif self.s_in == S.LEN2:
            self.len_in |= ci
            self.s_in = S.DATA

        elif self.s_in == S.DATA:
            self.m_in.add_chunk(ci,8)
            self.crc_in.update(ci)
            self.len_in -= 1
            if self.len_in == 0:
                self.s_in = S.CRC1
                self.crc_in = self.crc_in.finish()

        elif self.s_in == S.CRC1:
            self.crc_in ^= ci<<8
            self.s_in = S.CRC2

        elif self.s_in == S.CRC2:
            self.crc_in ^= ci
            self.set_timeout(False)

            if self.crc_in:
                self.report_error(ERR.CRC, msg=self.m_in)
                self.s_in = S.IDLE
            else:
                self.s_in = S.DONE
                self.process(self.m_in)
                self.send_ack()
            self.alloc_in()
            self.s_in = S.IDLE

        elif self.s_in == S.DONE:
            # ugh, overflow?
            self.report_error(ERR.OVERFLOW)


    def send_data(self, msg) -> bytes:
        """
        Generate chunk of bytes to send for this message.
        """
        res = bytearray()
        res.append(prio_data[msg.get('prio',1)])
        n_b = len(msg.data) + msg.header_len
        if n_b >= 0x80:
            res.append(0x80 | (n_b>>8))
            res.append(n_b & 0xFF)
        else:
            res.append(n_b)

        crc = CRC16()
        h = msg.header.bytes
        for b in h:
            crc.update(b)
            res.append(b)

        d = msg.data
        for b in d:
            crc.update(b)
            res.append(b)

        crc = crc.finish()
        res.append(crc>>8)
        res.append(crc&0xFF)
        return res


    def recv(self, prio=0):
        """
        Did we receive a message? if so, return it.
        """
        if self.s_in != S.DONE:
            return None

        msg = self.m_in
        msg.prio = self.prio_in
        self.alloc_in()
        return msg
        
    def timeout(self):
        """
        Call this periodically (e.g. every 10ms on 9600 baud) whenever
        `set_timeout` told you to.
        """
        if self.s_in != S.IDLE:
            self.idle += 1
            if self.idle > 3:
                self.idle = 0
                self.report_error(ERR.LOST)
                self.s_in = S.IDLE
                self.crc_in = CRC16()
                self.m_in.start_add()
                self.set_timeout(False)
        else:
            self.idle = 0
            if self.log_buf and self.log_buf_t+0.2 < self.now():
                self.dump_log_buf()

class SerBusDump(SerBus):
    """
    A SerBus version useable for debugging
    """
    _n = 0

    def report_error(self, typ, **kw):
        print("ERROR",typ,kw)

    def set_timeout(self, flag):
        pass
    
    def process(self, msg):
        print("MSG IN",msg)

    def process_ack(self):
        print("ACK")

    def data_out(self, data: bytes):
        print("SEND",repr(data))

    def now(self):
        self._n += 1
        return self._n

    def dump_log_buf(self):
        if not self.log_buf:
            return
        try:
            b = self.log_buf.decode("utf-8")
        except Exception:
            b = self.log_buf.decode("latin1")
        if b in {"L1","L2","L3"}:
            print(self.spinner[self.spin_pos],end="\r")
            sys.stdout.flush()
            self.spin_pos = (self.spin_pos+1) % len(self.spinner)
        else:
            print("LOG", b);
        self.log_buf = b""

