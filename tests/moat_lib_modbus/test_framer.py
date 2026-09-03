"""Tests for :mod:`moat.lib.modbus.framer`."""

from __future__ import annotations

from moat.lib.modbus.framer import FramerRTU, FramerTCP
from moat.lib.modbus.pdu import (
    ExceptionResponse,
    ReadCoilsRequest,
    ReadCoilsResponse,
    ReadDiscreteInputsRequest,
    ReadDiscreteInputsResponse,
    ReadHoldingRegistersRequest,
    ReadHoldingRegistersResponse,
    ReadInputRegistersRequest,
    ReadInputRegistersResponse,
    WriteMultipleCoilsRequest,
    WriteMultipleCoilsResponse,
    WriteMultipleRegistersRequest,
    WriteMultipleRegistersResponse,
    WriteSingleCoilRequest,
    WriteSingleCoilResponse,
    WriteSingleRegisterRequest,
    WriteSingleRegisterResponse,
)

# --------------------------------------------------------------------------- #
# TCP framer round-trip tests
# --------------------------------------------------------------------------- #


def test_tcp_roundtrip_holding_registers():
    """FramerTCP round-trips a holding-registers request and response."""
    # Server framer decodes requests; client framer decodes responses
    srv_fr = FramerTCP(True)
    cli_fr = FramerTCP(False)

    # Build a request on the client side, decode on the server side
    req = ReadHoldingRegistersRequest(address=100, count=5, unit_id=1, transaction_id=42)
    frame = cli_fr.buildFrame(req)
    used, pdu = srv_fr.handleFrame(frame)
    assert used == len(frame)
    assert isinstance(pdu, ReadHoldingRegistersRequest)
    assert pdu.address == 100
    assert pdu.count == 5
    assert pdu.unit_id == 1
    assert pdu.transaction_id == 42

    # Build a response on the server side, decode on the client side
    resp = ReadHoldingRegistersResponse(registers=[1, 2, 3], unit_id=1, transaction_id=42)
    frame = srv_fr.buildFrame(resp)
    used, pdu = cli_fr.handleFrame(frame)
    assert used == len(frame)
    assert isinstance(pdu, ReadHoldingRegistersResponse)
    assert pdu.registers == [1, 2, 3]
    assert pdu.unit_id == 1
    assert pdu.transaction_id == 42


def test_tcp_roundtrip_all_kinds():
    """FramerTCP round-trips all four register kinds."""
    srv_fr = FramerTCP(True)
    cli_fr = FramerTCP(False)

    for req_cls, _resp_cls, kwargs in [
        (ReadCoilsRequest, ReadCoilsResponse, {"address": 10, "count": 5}),
        (ReadDiscreteInputsRequest, ReadDiscreteInputsResponse, {"address": 20, "count": 3}),
        (ReadHoldingRegistersRequest, ReadHoldingRegistersResponse, {"address": 30, "count": 4}),
        (ReadInputRegistersRequest, ReadInputRegistersResponse, {"address": 40, "count": 2}),
    ]:
        req = req_cls(**kwargs, unit_id=1, transaction_id=1)
        frame = cli_fr.buildFrame(req)
        used, pdu = srv_fr.handleFrame(frame)
        assert used == len(frame)
        assert isinstance(pdu, req_cls)

    # Write PDUs
    write_tests = [
        (WriteSingleCoilRequest, WriteSingleCoilResponse, {"address": 10, "bits": [True]}),
        (
            WriteSingleRegisterRequest,
            WriteSingleRegisterResponse,
            {"address": 20, "registers": [42]},
        ),
        (
            WriteMultipleCoilsRequest,
            WriteMultipleCoilsResponse,
            {"address": 30, "bits": [True, False, True]},
        ),
        (
            WriteMultipleRegistersRequest,
            WriteMultipleRegistersResponse,
            {"address": 40, "registers": [1, 2, 3]},
        ),
    ]
    for req_cls, _resp_cls, kwargs in write_tests:
        req = req_cls(**kwargs, unit_id=1, transaction_id=1)
        frame = cli_fr.buildFrame(req)
        used, pdu = srv_fr.handleFrame(frame)
        assert used == len(frame)
        assert isinstance(pdu, req_cls)


def test_tcp_partial_frame():
    """Feeding the first half of a TCP frame returns (0, None)."""
    srv_fr = FramerTCP(True)
    req = ReadHoldingRegistersRequest(address=100, count=5, unit_id=1, transaction_id=42)
    frame = srv_fr.buildFrame(req)

    # Feed first half
    half = len(frame) // 2
    used, pdu = srv_fr.handleFrame(frame[:half])
    assert used == 0
    assert pdu is None

    # Feed the rest
    used, pdu = srv_fr.handleFrame(frame[half:])
    assert isinstance(pdu, ReadHoldingRegistersRequest)
    assert pdu.address == 100


def test_tcp_role_asymmetry():
    """A request built by a server-role framer decodes as a request."""
    srv_fr = FramerTCP(True)
    cli_fr = FramerTCP(False)

    req = ReadHoldingRegistersRequest(address=100, count=5, unit_id=1)
    frame = srv_fr.buildFrame(req)

    # Server framer decodes as request
    _, pdu = srv_fr.handleFrame(frame)
    assert isinstance(pdu, ReadHoldingRegistersRequest)

    # Client framer decodes same bytes as response
    _used, pdu = cli_fr.handleFrame(frame)
    assert isinstance(pdu, ReadHoldingRegistersResponse)


def test_tcp_reset_frame():
    """resetFrame clears the accumulator."""
    srv_fr = FramerTCP(True)
    req = ReadHoldingRegistersRequest(address=100, count=5, unit_id=1)
    frame = srv_fr.buildFrame(req)

    # Feed partial frame
    srv_fr.handleFrame(frame[:3])
    srv_fr.resetFrame()
    assert srv_fr._buffer == bytearray()  # noqa: SLF001

    # Full frame should now decode cleanly
    _used, pdu = srv_fr.handleFrame(frame)
    assert isinstance(pdu, ReadHoldingRegistersRequest)


def test_tcp_role_string_aliases():
    """Role accepts string aliases 'server'/'client'."""
    srv_fr = FramerTCP("server")
    cli_fr = FramerTCP("client")
    assert srv_fr.role_is_server is True
    assert cli_fr.role_is_server is False


# --------------------------------------------------------------------------- #
# RTU framer round-trip tests
# --------------------------------------------------------------------------- #


def test_rtu_roundtrip_holding_registers():
    """FramerRTU round-trips a holding-registers request and response."""
    srv_fr = FramerRTU(True)
    cli_fr = FramerRTU(False)

    req = ReadHoldingRegistersRequest(address=100, count=5, unit_id=1)
    frame = cli_fr.buildFrame(req)
    used, pdu = srv_fr.handleFrame(frame)
    assert used == len(frame)
    assert isinstance(pdu, ReadHoldingRegistersRequest)
    assert pdu.address == 100
    assert pdu.count == 5
    assert pdu.unit_id == 1

    resp = ReadHoldingRegistersResponse(registers=[1, 2, 3], unit_id=1)
    frame = srv_fr.buildFrame(resp)
    used, pdu = cli_fr.handleFrame(frame)
    assert used == len(frame)
    assert isinstance(pdu, ReadHoldingRegistersResponse)
    assert pdu.registers == [1, 2, 3]


def test_rtu_roundtrip_all_kinds():
    """FramerRTU round-trips all PDU kinds."""
    srv_fr = FramerRTU(True)
    cli_fr = FramerRTU(False)

    for req_cls, kwargs in [
        (ReadCoilsRequest, {"address": 10, "count": 5}),
        (ReadDiscreteInputsRequest, {"address": 20, "count": 3}),
        (ReadHoldingRegistersRequest, {"address": 30, "count": 4}),
        (ReadInputRegistersRequest, {"address": 40, "count": 2}),
        (WriteSingleCoilRequest, {"address": 10, "bits": [True]}),
        (WriteSingleRegisterRequest, {"address": 20, "registers": [42]}),
        (WriteMultipleCoilsRequest, {"address": 30, "bits": [True, False, True]}),
        (WriteMultipleRegistersRequest, {"address": 40, "registers": [1, 2, 3]}),
    ]:
        req = req_cls(**kwargs, unit_id=1)
        frame = cli_fr.buildFrame(req)
        used, pdu = srv_fr.handleFrame(frame)
        assert used == len(frame), (
            f"Failed for {req_cls.__name__}: used={used}, frame_len={len(frame)}"
        )
        assert isinstance(pdu, req_cls), f"Expected {req_cls.__name__}, got {type(pdu).__name__}"


def test_rtu_crc_mismatch_recovery():
    """A corrupted RTU frame is rejected and scanning resumes."""
    # Use matching roles: client builds response, client framer decodes it
    cli_fr = FramerRTU(False)
    resp = ReadHoldingRegistersResponse(registers=[1, 2, 3], unit_id=1)
    good_frame = cli_fr.buildFrame(resp)

    # Corrupt one payload byte
    bad_frame = bytearray(good_frame)
    bad_frame[3] ^= 0xFF  # Flip bits in the PDU

    # Append a valid frame after the bad one
    combined = bytes(bad_frame) + good_frame

    # Feed all data to a client framer (decodes responses).
    # The framer scans through bad bytes until it finds the valid frame.
    srv_fr = FramerRTU(False)
    _used, pdu = srv_fr.handleFrame(combined)

    # The framer should have consumed the bad frame bytes and found
    # the valid frame.
    assert pdu is not None, "Should have decoded the valid frame"
    assert isinstance(pdu, ReadHoldingRegistersResponse)
    assert pdu.registers == [1, 2, 3]


def test_rtu_partial_frame():
    """Feeding partial RTU data returns (0, None)."""
    srv_fr = FramerRTU(True)
    req = ReadHoldingRegistersRequest(address=100, count=5, unit_id=1)
    frame = srv_fr.buildFrame(req)

    # Feed first 3 bytes (need at least 4 for min frame)
    used, pdu = srv_fr.handleFrame(frame[:3])
    assert used == 0
    assert pdu is None

    # Feed the rest
    used, pdu = srv_fr.handleFrame(frame[3:])
    assert isinstance(pdu, ReadHoldingRegistersRequest)


def test_rtu_reset_frame():
    """resetFrame clears the RTU accumulator."""
    srv_fr = FramerRTU(True)
    req = ReadHoldingRegistersRequest(address=100, count=5, unit_id=1)
    frame = srv_fr.buildFrame(req)

    srv_fr.handleFrame(frame[:3])
    srv_fr.resetFrame()
    assert srv_fr._buffer == bytearray()  # noqa: SLF001

    _used, pdu = srv_fr.handleFrame(frame)
    assert isinstance(pdu, ReadHoldingRegistersRequest)


def test_rtu_exception_response():
    """RTU framer handles exception responses."""
    cli_fr = FramerRTU(False)
    srv_fr = FramerRTU(True)

    exc = ExceptionResponse(function_code=3, exception_code=2)
    exc.unit_id = 1
    frame = srv_fr.buildFrame(exc)

    used, pdu = cli_fr.handleFrame(frame)
    assert used == len(frame)
    assert isinstance(pdu, ExceptionResponse)
    assert pdu.function_code == 3
    assert pdu.exception_code == 2
