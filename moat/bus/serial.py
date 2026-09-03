"""
Code to (de)serialize bus messages
"""

from __future__ import annotations

import logging
import sys
from enum import IntEnum

import trio

from .crc import CRC16
from .message import BusMessage

from typing import Any

logger = logging.getLogger(__name__)


class S(IntEnum):
    "State machine"

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
    "Errors"

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
    spinner = ["/", "-", "\\", "|"]
    spin_pos = 0

    m_in: BusMessage | None
    crc_in: CRC16 | int
    len_in: int
    prio_in: int
    crc_out: int
    s_in: S
    idle: int
    log_buf: bytes
    log_buf_t: float

    def __init__(self) -> None:
        # incoming
        self.m_in = None  # bus message
        self.crc_in = 0
        self.len_in = 0
        self.prio_in = 0

        # outgoing
        self.crc_out = 0

        self.s_in = S.IDLE

        self.idle = 0  # counter, to drop partial messages
        self.alloc_in()

        self.log_buf = b""

    def report_error(self, typ: ERR, **kw: Any) -> None:
        """
        OVERRIDE: There's been a comm problem.
        """
        raise NotImplementedError("Override me")

    def set_timeout(self, flag: bool) -> None:
        """
        OVERRIDE: Arrange to periodically call .timeout, or not,
        depending on whether @flag is True, or not.
        """
        raise NotImplementedError("Override me")

    def process(self, msg: BusMessage) -> None:
        """
        OVERRIDE: Process this message.
        """
        raise NotImplementedError("Override me")

    def process_ack(self) -> None:
        """
        OVERRIDE: Process this incoming ACK.
        """
        raise NotImplementedError("Override me")

    def data_out(self, data: bytes) -> None:
        """
        OVERRIDE: Send these serial data.
        """
        raise NotImplementedError("Override me")

    def alloc_in(self) -> None:
        """Allocate a fresh incoming message buffer."""
        self.m_in = BusMessage()
        self.crc_in = CRC16()
        self.m_in.start_add()

    def send(self, msg: BusMessage) -> None:
        """
        Queue a message.
        """
        self.data_out(self.send_data(msg))

    def send_ack(self) -> None:
        """
        Queue an ACK.
        """
        self.data_out(b"\x06")

    def dump_log_buf(self) -> None:
        """Flush the log buffer to the logger."""
        if not self.log_buf:
            return
        try:
            b = self.log_buf.decode("utf-8", errors="surrogateescape")
        except Exception:
            b = self.log_buf.decode("latin1")
        if b in {"L1", "L2", "L3"}:
            print(self.spinner[self.spin_pos], end="\r")
            sys.stdout.flush()
            self.spin_pos = (self.spin_pos + 1) % len(self.spinner)
        else:
            logger.debug("R: %s", b)
        self.log_buf = b""

    @staticmethod
    def now() -> float:
        """Return the current monotonic time."""
        return trio.current_time()

    def char_in(self, ci: int) -> None:
        """
        Process an incoming serial character.
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
            elif ci not in (10, 13):  # CR/LF
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
            assert self.m_in is not None
            self.m_in.add_chunk(ci, 8)
            assert isinstance(self.crc_in, CRC16)
            self.crc_in.update(ci)
            self.len_in -= 1
            if self.len_in == 0:
                self.s_in = S.CRC1
                self.crc_in = self.crc_in.finish()

        elif self.s_in == S.CRC1:
            assert isinstance(self.crc_in, int)
            self.crc_in = self.crc_in ^ (ci << 8)
            self.s_in = S.CRC2

        elif self.s_in == S.CRC2:
            assert isinstance(self.crc_in, int)
            self.crc_in = self.crc_in ^ ci
            self.set_timeout(False)

            if self.crc_in:
                self.report_error(ERR.CRC, msg=self.m_in)
                self.s_in = S.IDLE
            else:
                self.s_in = S.DONE
                assert self.m_in is not None
                self.process(self.m_in)
                self.send_ack()
            self.alloc_in()
            self.s_in = S.IDLE

        elif self.s_in == S.DONE:
            # ugh, overflow?
            self.report_error(ERR.OVERFLOW)

    def send_data(self, msg: BusMessage) -> bytes:
        """
        Generate chunk of bytes to send for this message.
        """
        res = bytearray()
        res.append(self.prio_data[getattr(msg, "prio", 1)])
        n_b = len(msg.data) + msg.header_len
        if n_b >= 0x80:
            res.append(0x80 | (n_b >> 8))
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
        res.append(crc >> 8)
        res.append(crc & 0xFF)
        return bytes(res)

    def recv(self) -> BusMessage | None:
        """
        Did we receive a message? if so, return it.
        """
        if self.s_in != S.DONE:
            return None

        msg = self.m_in
        assert msg is not None
        msg.prio = self.prio_in
        self.alloc_in()
        return msg

    def timeout(self) -> None:
        """
        Call this periodically (e.g. every 10ms on 9600 baud) whenever
        ``set_timeout`` told you to.
        """
        if self.s_in != S.IDLE:
            self.idle += 1
            if self.idle > 3:
                self.idle = 0
                self.report_error(ERR.LOST)
                self.s_in = S.IDLE
                self.crc_in = CRC16()
                assert self.m_in is not None
                self.m_in.start_add()
                self.set_timeout(False)
        else:
            self.idle = 0
            if self.log_buf and self.log_buf_t + 0.2 < self.now():
                self.dump_log_buf()


class SerBusDump(SerBus):
    """
    A SerBus version useable for debugging.
    """

    _n = 0

    def report_error(self, typ: ERR, **kw: Any) -> None:
        """Print errors."""
        print("ERROR", typ, kw)

    def set_timeout(self, flag: bool) -> None:
        """No-op timeout."""

    def process(self, msg: BusMessage) -> None:
        """Print received messages."""
        print("MSG IN", msg)

    def process_ack(self) -> None:
        """Print ACKs."""
        print("ACK")

    def data_out(self, data: bytes) -> None:
        """Print sent data."""
        print("SEND", repr(data))

    def now(self) -> float:
        """Return a synthetic monotonic clock."""
        self._n += 1
        return self._n

    def dump_log_buf(self) -> None:
        """Flush the log buffer."""
        if not self.log_buf:
            return
        try:
            b = self.log_buf.decode("utf-8", errors="surrogateescape")
        except Exception:
            b = self.log_buf.decode("latin1")
        if b in {"L1", "L2", "L3"}:
            print(self.spinner[self.spin_pos], end="\r")
            sys.stdout.flush()
            self.spin_pos = (self.spin_pos + 1) % len(self.spinner)
        else:
            print("LOG", b)
        self.log_buf = b""
