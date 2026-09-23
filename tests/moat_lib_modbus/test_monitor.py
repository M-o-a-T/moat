"""Tests for the RTU monitor-mode framer (:class:`FramerRTU` with ``role="monitor"``).

Monitor mode is a passive bus sniffer: sending is prohibited, and received
frames are decoded as an alternating request/response sequence starting with
a request.  These tests pin the contract described in :class:`FramerRTU`'s
docstring.
"""

from __future__ import annotations

import pytest

from moat.lib.modbus.errors import ModbusIOError
from moat.lib.modbus.framer import FramerRTU, FramerTCP
from moat.lib.modbus.pdu import (
    ExceptionResponse,
    ReadCoilsRequest,
    ReadCoilsResponse,
    ReadHoldingRegistersRequest,
    ReadHoldingRegistersResponse,
    WriteMultipleRegistersRequest,
    WriteMultipleRegistersResponse,
    WriteSingleRegisterRequest,
    WriteSingleRegisterResponse,
)

# --------------------------------------------------------------------------- #
# Construction / role resolution
# --------------------------------------------------------------------------- #


def test_monitor_construction_defaults():
    """A monitor framer starts expecting a request."""
    fr = FramerRTU("monitor")
    assert fr.is_monitor is True
    assert fr.expecting_request is True


def test_monitor_case_insensitive():
    """The ``monitor`` role token is case-insensitive."""
    for tok in ("monitor", "MONITOR", "Monitor"):
        fr = FramerRTU(tok)
        assert fr.is_monitor is True
        assert fr.expecting_request is True


def test_monitor_not_supported_on_tcp():
    """Monitor mode is RTU-only; FramerTCP rejects it."""
    with pytest.raises(ValueError):  # noqa:PT011
        FramerTCP("monitor")


def test_fixed_roles_unaffected():
    """Non-monitor framers keep their original behaviour and expose no phase flip."""
    srv = FramerRTU(True)
    cli = FramerRTU(False)
    assert srv.is_monitor is False
    assert cli.is_monitor is False
    assert srv.expecting_request is True
    assert cli.expecting_request is False
    # Fixed-role framers never flip phase on decode.
    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    frame = cli.buildFrame(req)
    used, _pdu = srv.handleFrame(frame)
    assert used == len(frame)
    assert srv.expecting_request is True


# --------------------------------------------------------------------------- #
# Sending is prohibited
# --------------------------------------------------------------------------- #


def test_monitor_buildframe_raises():
    """buildFrame is forbidden in monitor mode."""
    fr = FramerRTU("monitor")
    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    with pytest.raises(ModbusIOError):
        fr.buildFrame(req)


# --------------------------------------------------------------------------- #
# Alternating request/response decoding
# --------------------------------------------------------------------------- #


def test_monitor_alternates_request_then_response():
    """A request frame decodes as a request, then a response as a response."""
    fr = FramerRTU("monitor")

    # Build a request frame (using a throwaway client framer) and a matching
    # response frame (using a throwaway server framer).
    builder_cli = FramerRTU(False)
    builder_srv = FramerRTU(True)

    req = ReadHoldingRegistersRequest(address=100, count=3, unit_id=1)
    resp = ReadHoldingRegistersResponse(registers=[10, 20, 30], unit_id=1)

    req_frame = builder_cli.buildFrame(req)
    resp_frame = builder_srv.buildFrame(resp)

    # Phase 1: expecting a request.
    assert fr.expecting_request is True
    used, pdu = fr.handleFrame(req_frame)
    assert used == len(req_frame)
    assert isinstance(pdu, ReadHoldingRegistersRequest)
    assert pdu.address == 100
    assert pdu.count == 3
    assert pdu.unit_id == 1

    # Phase flipped: now expecting a response.
    assert fr.expecting_request is False

    used, pdu = fr.handleFrame(resp_frame)
    assert used == len(resp_frame)
    assert isinstance(pdu, ReadHoldingRegistersResponse)
    assert pdu.registers == [10, 20, 30]

    # Phase flipped again: back to expecting a request.
    assert fr.expecting_request is True


def test_monitor_two_cycles():
    """Two consecutive request/response pairs alternate correctly."""
    fr = FramerRTU("monitor")
    builder_cli = FramerRTU(False)
    builder_srv = FramerRTU(True)

    for cycle in range(2):
        req = ReadCoilsRequest(address=cycle * 10, count=4, unit_id=2)
        resp = ReadCoilsResponse(bits=[True, False, True, False], unit_id=2)
        req_frame = builder_cli.buildFrame(req)
        resp_frame = builder_srv.buildFrame(resp)

        assert fr.expecting_request is True, f"cycle {cycle}: expected request phase"
        _u, pdu_req = fr.handleFrame(req_frame)
        assert isinstance(pdu_req, ReadCoilsRequest)

        assert fr.expecting_request is False, f"cycle {cycle}: expected response phase"
        _u, pdu_resp = fr.handleFrame(resp_frame)
        assert isinstance(pdu_resp, ReadCoilsResponse)


def test_monitor_writes_too():
    """Write requests/responses alternate just like reads."""
    fr = FramerRTU("monitor")
    builder_cli = FramerRTU(False)
    builder_srv = FramerRTU(True)

    req = WriteSingleRegisterRequest(address=5, registers=[0xABCD], unit_id=3)
    resp = WriteSingleRegisterResponse(address=5, registers=[0xABCD], unit_id=3)
    req_frame = builder_cli.buildFrame(req)
    resp_frame = builder_srv.buildFrame(resp)

    _u, pdu_req = fr.handleFrame(req_frame)
    assert isinstance(pdu_req, WriteSingleRegisterRequest)
    assert fr.expecting_request is False

    _u, pdu_resp = fr.handleFrame(resp_frame)
    assert isinstance(pdu_resp, WriteSingleRegisterResponse)
    assert fr.expecting_request is True


def test_monitor_exception_response_decodes_as_response():
    """An exception response is decoded in the response phase."""
    fr = FramerRTU("monitor")
    builder_cli = FramerRTU(False)
    builder_srv = FramerRTU(True)

    # Request phase.
    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    _u, _p = fr.handleFrame(builder_cli.buildFrame(req))
    assert fr.expecting_request is False

    # Slave answers with an exception.
    exc = ExceptionResponse(function_code=3, exception_code=2)
    exc.unit_id = 1
    exc_frame = builder_srv.buildFrame(exc)

    _u, pdu = fr.handleFrame(exc_frame)
    assert isinstance(pdu, ExceptionResponse)
    assert pdu.function_code == 3
    assert pdu.exception_code == 2
    assert fr.expecting_request is True


# --------------------------------------------------------------------------- #
# Resetting the phase: no-reply / torn-frame scenarios
# --------------------------------------------------------------------------- #


def test_monitor_reset_returns_to_request_phase_from_response_pending():
    """After a request, resetFrame() returns to expecting a request.

    Models a silent slave: the master sent a request, no reply ever came,
    the caller fires the inter-frame timeout and calls resetFrame().
    """
    fr = FramerRTU("monitor")
    builder_cli = FramerRTU(False)

    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    _u, _p = fr.handleFrame(builder_cli.buildFrame(req))
    assert fr.expecting_request is False  # now waiting for a reply

    fr.resetFrame()
    assert fr.expecting_request is True  # back to expecting a request


def test_monitor_reset_clears_torn_partial_request():
    """A torn partial request + reset recovers to a clean request decode.

    Models a garbled request: some bytes arrived, the inter-frame timeout
    fired, resetFrame() dropped them, and the next frame is a fresh request.
    """
    fr = FramerRTU("monitor")
    builder_cli = FramerRTU(False)

    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    req_frame = builder_cli.buildFrame(req)

    # Feed a torn fragment (too short to decode).
    used, pdu = fr.handleFrame(req_frame[:3])
    assert used == 0
    assert pdu is None
    assert fr.expecting_request is True  # phase untouched by a failed decode

    # Timeout: reset.
    fr.resetFrame()
    assert fr.expecting_request is True

    # Next frame is a fresh request.
    used, pdu = fr.handleFrame(req_frame)
    assert used == len(req_frame)
    assert isinstance(pdu, ReadHoldingRegistersRequest)


def test_monitor_reset_does_not_disturb_fixed_role():
    """resetFrame() on a non-monitor framer behaves as before (just clears bytes)."""
    srv = FramerRTU(True)
    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    frame = srv.buildFrame(req)
    srv.handleFrame(frame[:3])
    srv.resetFrame()
    assert srv._buffer == bytearray()  # noqa: SLF001
    assert srv.expecting_request is True


# --------------------------------------------------------------------------- #
# Streaming / accumulation across feeds
# --------------------------------------------------------------------------- #


def test_monitor_streams_byte_by_byte():
    """Bytes arriving one at a time accumulate and decode once complete.

    Each byte is fed exactly once (no caller-side re-feed), mirroring a
    serial stream where every received byte is handed straight to the
    framer.  The framer retains unconsumed bytes internally until a full
    frame is assembled.
    """
    fr = FramerRTU("monitor")
    builder_cli = FramerRTU(False)
    builder_srv = FramerRTU(True)

    req = ReadHoldingRegistersRequest(address=7, count=1, unit_id=4)
    resp = ReadHoldingRegistersResponse(registers=[0x1234], unit_id=4)
    blob = builder_cli.buildFrame(req) + builder_srv.buildFrame(resp)

    seen: list[type] = []
    for i in range(len(blob)):
        _used, pdu = fr.handleFrame(blob[i : i + 1])
        if pdu is not None:
            seen.append(type(pdu))

    assert seen == [ReadHoldingRegistersRequest, ReadHoldingRegistersResponse]
    assert fr.expecting_request is True


def test_monitor_back_to_back_frames_in_one_feed():
    """A request and its reply delivered together decode in order."""
    fr = FramerRTU("monitor")
    builder_cli = FramerRTU(False)
    builder_srv = FramerRTU(True)

    req = WriteMultipleRegistersRequest(address=10, registers=[1, 2, 3], unit_id=5)
    resp = WriteMultipleRegistersResponse(address=10, count=3, unit_id=5)
    blob = builder_cli.buildFrame(req) + builder_srv.buildFrame(resp)

    pdus: list[type] = []
    data = bytes(blob)
    while data:
        used, pdu = fr.handleFrame(data)
        if pdu is not None:
            pdus.append(type(pdu))
        if not used:
            break
        data = data[used:]

    assert pdus == [WriteMultipleRegistersRequest, WriteMultipleRegistersResponse]
    assert fr.expecting_request is True


# --------------------------------------------------------------------------- #
# CRC rejection interacts sanely with the phase
# --------------------------------------------------------------------------- #


def test_monitor_crc_corruption_keeps_phase_until_valid_frame():
    """Corrupted bytes are skipped; the phase only advances on a valid frame."""
    fr = FramerRTU("monitor")
    builder_cli = FramerRTU(False)

    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    good = builder_cli.buildFrame(req)

    # Prepend a corrupted copy of the request (bad CRC).
    bad = bytearray(good)
    bad[3] ^= 0xFF
    blob = bytes(bad) + good

    _used, pdu = fr.handleFrame(blob)
    assert pdu is not None
    assert isinstance(pdu, ReadHoldingRegistersRequest)
    assert pdu.address == 1
    # A request was decoded -> phase advanced to expecting a response.
    assert fr.expecting_request is False


def test_monitor_unknown_fc_skipped():
    """Unknown function-code bytes are skipped without disturbing the phase."""
    fr = FramerRTU("monitor")
    builder_cli = FramerRTU(False)

    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    good = builder_cli.buildFrame(req)

    # Lead with junk containing an unsupported FC (0xAA) framed-ish bytes.
    # The framer cannot size it, so it skips byte-by-byte until the valid frame.
    junk = bytes([0x01, 0xAA, 0x00, 0x00, 0x12, 0x34])
    blob = junk + good

    _used, pdu = fr.handleFrame(blob)
    assert pdu is not None
    assert isinstance(pdu, ReadHoldingRegistersRequest)
    assert fr.expecting_request is False
