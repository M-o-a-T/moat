"""
Modbus TCP (MBAP) and RTU framers.

Provides :class:`FramerTCP` and :class:`FramerRTU`, each constructed
with a required *role* flag:

- ``True`` / ``"server"`` -- decode incoming bytes as **requests**.
- ``False`` / ``"client"`` -- decode incoming bytes as **responses**.
- ``"monitor"`` -- (**RTU only**) passive bus sniffer: decode alternating
  request/response frames, starting with a request.  Sending is
  prohibited; see :class:`FramerRTU`.

Both share the contract::

    buildFrame(msg) -> bytes
    handleFrame(data, ...) -> (used: int, pdu: PDU | None)
    resetFrame()

where ``used == 0`` signals "frame incomplete, feed more bytes".

Internally each framer holds a private byte accumulator (the only
mutable state permitted under the sans-IO rule) and delegates PDU
decoding to :func:`moat.lib.modbus.pdu.decode_pdu` with the role flag.
"""

from __future__ import annotations

import struct

from ._crc import crc16
from .errors import ModbusIOError
from .pdu import PDU, decode_pdu

import typing

_ROLE_ALIASES: dict[object, bool] = {
    True: True,
    False: False,
    "server": True,
    "client": False,
    "Server": True,
    "Client": False,
}


def _resolve_role(role: typing.Any) -> bool:
    """Resolve a role flag to a boolean (True = server)."""
    if isinstance(role, bool):
        return role
    if isinstance(role, str):
        r = _ROLE_ALIASES.get(role)
        if r is not None:
            return r
    raise ValueError(f"Invalid role: {role!r}; use True/False or 'server'/'client'")


# MBAP header: 7 bytes
#   transaction_id (2) + protocol_id (2) + length (2) + unit_id (1)
_MBAP_HEADER_SIZE = 7


class _FramerBase:
    """Common base for Modbus framers.

    Owns the receive byte accumulator -- the only mutable state permitted
    under the sans-IO rule -- and exposes the parts of the framer contract
    that are independent of the wire format: :attr:`pending` and
    :meth:`resetFrame`.  Subclasses provide :meth:`buildFrame` and
    :meth:`handleFrame`.
    """

    _buffer: bytearray

    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def pending(self) -> int:
        """Number of buffered bytes awaiting more data to complete a frame.

        Non-zero means a partial frame is in progress; the caller may use
        this to decide whether to arm an inter-frame (idle-gap) timeout.
        """
        return len(self._buffer)

    def resetFrame(self) -> None:
        """Clear the internal byte accumulator."""
        self._buffer = bytearray()


class FramerTCP(_FramerBase):
    """Modbus TCP framer (MBAP).

    Args:
        role: ``True`` / ``"server"`` to decode incoming bytes as
            requests; ``False`` / ``"client"`` to decode as responses.
    """

    def __init__(self, role: typing.Any) -> None:
        if isinstance(role, str) and role.lower() == "monitor":
            raise ValueError("Monitor mode is only supported for RTU (FramerRTU)")
        self.role_is_server: bool = _resolve_role(role)
        self.is_monitor: bool = False
        super().__init__()

    def buildFrame(self, msg: PDU) -> bytes:
        """Build an MBAP-framed TCP message from *msg*."""
        pdu = msg.encode_frame()
        unit_id = getattr(msg, "unit_id", 0)
        tid = getattr(msg, "transaction_id", 0)
        length = len(pdu) + 1  # PDU + unit_id byte
        header = struct.pack(">HHHBB", tid, 0, length, unit_id, 0)
        # Actually MBAP is: tid(2) + proto_id(2) + length(2) + unit_id(1)
        # length includes unit_id + PDU
        header = struct.pack(">HHHB", tid, 0, length, unit_id)
        return header + pdu

    def handleFrame(self, data: bytes, *_args: typing.Any) -> tuple[int, PDU | None]:
        """Try to parse a complete frame from *data*.

        Returns ``(used, pdu)`` where ``used`` is the number of bytes
        consumed and ``pdu`` is the decoded PDU (or ``None`` if the
        frame is incomplete).  ``used == 0`` means "need more bytes".
        """
        self._buffer.extend(data)

        if len(self._buffer) < _MBAP_HEADER_SIZE:
            return 0, None

        tid, proto_id, length, unit_id = struct.unpack(
            ">HHHB", bytes(self._buffer[:_MBAP_HEADER_SIZE])
        )

        if proto_id != 0:
            raise ModbusIOError(f"Invalid MBAP protocol id: {proto_id}")

        total_len = _MBAP_HEADER_SIZE + (length - 1)  # length includes unit_id
        if len(self._buffer) < total_len:
            return 0, None

        pdu_bytes = bytes(self._buffer[_MBAP_HEADER_SIZE:total_len])
        # Consume the frame
        self._buffer = self._buffer[total_len:]

        pdu = decode_pdu(pdu_bytes, server=self.role_is_server)
        pdu.transaction_id = tid
        pdu.unit_id = unit_id
        return total_len, pdu


class FramerRTU(_FramerBase):
    """Modbus RTU framer (serial).

    Args:
        role: ``True`` / ``"server"`` to decode incoming bytes as
            requests; ``False`` / ``"client"`` to decode as responses;
            ``"monitor"`` for passive bus sniffing (RTU only).

    **Monitor mode** (``role="monitor"``) turns the framer into a passive
    bus sniffer.  Sending is prohibited: :meth:`buildFrame` raises
    :class:`~moat.lib.modbus.errors.ModbusIOError`.  Received frames are
    decoded as an alternating request/response sequence, starting with a
    request: each successfully decoded frame flips the expectation, so a
    request is followed by a response, then the next request, and so on.

    A Modbus RTU bus is strict master/slave: after a request the next
    frame is either the slave's reply or -- if the slave stays silent --
    nothing.  Because the framer is sans-IO it cannot measure the idle
    gap itself; the *caller* must signal "no reply / stalled frame" by
    calling :meth:`resetFrame`, which clears the accumulator and returns
    the framer to expecting a request.  In monitor mode :meth:`resetFrame`
    therefore always resets the phase to "expecting a request", regardless
    of which frame was pending.  Do **not** call :meth:`resetFrame` after
    a successfully decoded frame -- only on an inter-frame timeout.

    The current phase is queryable via :attr:`expecting_request`.
    """

    def __init__(self, role: typing.Any) -> None:
        if isinstance(role, str) and role.lower() == "monitor":
            self.is_monitor: bool = True
            # Initial phase: expect a request (server-like decoding).
            self.role_is_server: bool = True
            self._expect_request: bool = True
        else:
            self.is_monitor = False
            self.role_is_server = _resolve_role(role)
            self._expect_request = self.role_is_server
        super().__init__()

    @property
    def expecting_request(self) -> bool:
        """Whether the next frame is decoded as a request.

        In monitor mode this tracks the alternating request/response
        phase; for a fixed-role framer it mirrors the constructor role
        flag (a server expects requests, a client expects responses).
        """
        return self._expect_request

    @property
    def _decoding_server(self) -> bool:
        """Effective role flag for the current decode (monitor-aware)."""
        return self._expect_request if self.is_monitor else self.role_is_server

    def buildFrame(self, msg: PDU) -> bytes:
        """Build an RTU-framed message from *msg*.

        Raises:
            ModbusIOError: in monitor mode (sending is prohibited).
        """
        if self.is_monitor:
            raise ModbusIOError("Monitor mode: sending is prohibited")
        pdu = msg.encode_frame()
        unit_id = getattr(msg, "unit_id", 0)
        frame = bytes([unit_id]) + pdu
        crc = crc16(frame)
        return frame + crc.to_bytes(2, "little")

    def handleFrame(self, data: bytes, *_args: typing.Any) -> tuple[int, PDU | None]:
        """Try to parse a complete RTU frame from *data*.

        RTU frames have no length prefix; a frame consists of
        ``address(1) + PDU + CRC(2)``.  We attempt to decode the PDU
        greedily: read the FC byte, determine the expected PDU size
        from the function code and (for reads) the byte-count field,
        validate the CRC, and return the PDU.

        Returns ``(used, pdu)`` where ``used == 0`` means "incomplete".
        If the CRC is invalid, the bad bytes are consumed and scanning
        resumes.
        """
        self._buffer.extend(data)

        # Scan through the buffer trying to find a valid frame.
        # On CRC mismatch, advance by one byte and retry.
        offset = 0
        while offset < len(self._buffer):
            remaining = bytes(self._buffer[offset:])

            # Need at least: address(1) + FC(1) + CRC(2) = 4 bytes
            if len(remaining) < 4:
                # Not enough data; keep what's left in the buffer
                break

            fc = remaining[1]  # noqa: F841

            # Estimate PDU payload size based on FC byte and role
            pdu_size = _estimate_pdu_size(remaining, self._decoding_server)
            if pdu_size is None:
                # Unknown FC -- can't determine size, advance one byte
                offset += 1
                continue

            frame_len = 1 + pdu_size + 2  # addr + PDU + CRC

            # Cap frame_len to a reasonable maximum to prevent
            # a corrupted byte_count from stalling the scanner.
            if frame_len > 256:
                # Unreasonable frame size: likely garbage, advance
                offset += 1
                continue

            if len(remaining) < frame_len:
                # Not enough data yet for this frame; wait for more
                break

            frame = remaining[:frame_len]
            payload = frame[:-2]
            crc_recv = int.from_bytes(frame[-2:], "little")
            crc_calc = crc16(payload)

            if crc_recv != crc_calc:
                # CRC mismatch: advance one byte and retry
                offset += 1
                continue

            # CRC valid: decode the PDU
            unit_id = frame[0]
            pdu_bytes = frame[1:-2]

            # Consume everything up to and including this frame
            consumed = offset + frame_len
            self._buffer = self._buffer[consumed:]

            pdu = decode_pdu(pdu_bytes, server=self._decoding_server)
            pdu.unit_id = unit_id
            pdu.transaction_id = 0  # RTU has no transaction ID
            if self.is_monitor:
                # Alternate the phase: a decoded frame is followed by its
                # counterpart (request -> response -> request ...).
                self._expect_request = not self._expect_request
            return consumed, pdu

        # If we scanned through some bad bytes, consume them
        if offset > 0:
            self._buffer = self._buffer[offset:]
            return offset, None

        return 0, None

    def resetFrame(self) -> None:
        """Clear the internal byte accumulator.

        In monitor mode this also returns the framer to expecting a
        request: a timeout means the pending frame (request or reply)
        did not arrive, so the next frame must be a new request.
        """
        super().resetFrame()
        if self.is_monitor:
            self._expect_request = True


def _estimate_pdu_size(buf: bytes, server: bool) -> int | None:
    """Estimate the PDU payload size (excluding FC byte) from the buffer.

    Returns the number of PDU bytes (including the FC byte), or None
    if the buffer is too short to determine the size.

    The buffer must contain at least: address(1) + FC(1) + ...
    """
    if len(buf) < 2:
        return None

    fc = buf[1]

    # Exception response: FC | 0x80 + exception_code(1)
    if fc & 0x80:
        return 2  # FC + exception_code

    # For requests (server=True) and responses (server=False),
    # the PDU sizes differ.
    if server:
        # Requests
        if fc in (1, 2, 3, 4):
            # Read requests: FC(1) + addr(2) + count(2) = 5
            return 5
        elif fc == 5:
            # Write single coil: FC(1) + addr(2) + value(2) = 5
            return 5
        elif fc == 6:
            # Write single register: FC(1) + addr(2) + value(2) = 5
            return 5
        elif fc == 15:
            # Write multiple coils: FC(1) + addr(2) + count(2) + bc(1) + data(bc)
            if len(buf) < 7:
                return None
            byte_count = buf[6]
            return 6 + byte_count
        elif fc == 16:
            # Write multiple registers: FC(1) + addr(2) + count(2) + bc(1) + data(bc)
            if len(buf) < 7:
                return None
            byte_count = buf[6]
            return 6 + byte_count
        else:
            return None
    else:
        # Responses
        if fc in (1, 2):
            # Read coils/discrete response: FC(1) + byte_count(1) + data(bc)
            if len(buf) < 3:
                return None
            byte_count = buf[2]
            return 2 + byte_count
        elif fc in (3, 4):
            # Read registers response: FC(1) + byte_count(1) + data(bc)
            if len(buf) < 3:
                return None
            byte_count = buf[2]
            return 2 + byte_count
        elif fc == 5:
            # Write single coil response: FC(1) + addr(2) + value(2) = 5
            return 5
        elif fc == 6:
            # Write single register response: FC(1) + addr(2) + value(2) = 5
            return 5
        elif fc == 15:
            # Write multiple coils response: FC(1) + addr(2) + count(2) = 5
            return 5
        elif fc == 16:
            # Write multiple registers response: FC(1) + addr(2) + count(2) = 5
            return 5
        else:
            return None
