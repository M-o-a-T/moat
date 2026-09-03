"""Tests for :mod:`moat.lib.modbus.pdu`."""

from __future__ import annotations

import struct

from moat.lib.modbus.errors import ExcCodes, ModbusIOError
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
    decode_pdu,
    execute_request,
)

# --------------------------------------------------------------------------- #
# Fake Context for execute tests
# --------------------------------------------------------------------------- #


class FakeContext:
    """In-memory fake Context for testing Request.execute."""

    def __init__(self) -> None:
        self.data: dict[str, dict[int, int]] = {
            "c": {},
            "d": {},
            "h": {},
            "i": {},
        }

    def get_values(self, kind: str, address: int, count: int) -> list[int]:
        """Get values from the fake store."""
        store = self.data[kind]
        result: list[int] = []
        for i in range(count):
            if address + i not in store:
                raise KeyError(address + i)
            result.append(store[address + i])
        return result

    def set_values(self, kind: str, address: int, values: list[int]) -> None:
        """Set values in the fake store."""
        store = self.data[kind]
        for i, v in enumerate(values):
            store[address + i] = v


# --------------------------------------------------------------------------- #
# Encode/decode round-trip tests
# --------------------------------------------------------------------------- #


def test_read_holding_registers_roundtrip():
    """ReadHoldingRegistersRequest encodes and decodes round-trip."""
    req = ReadHoldingRegistersRequest(address=100, count=5)
    raw = req.encode_frame()
    assert raw == bytes([3]) + struct.pack(">HH", 100, 5)

    decoded = decode_pdu(raw, server=True)
    assert isinstance(decoded, ReadHoldingRegistersRequest)
    assert decoded.address == 100
    assert decoded.count == 5

    resp = ReadHoldingRegistersResponse(registers=[1, 2, 3])
    raw = resp.encode_frame()
    decoded = decode_pdu(raw, server=False)
    assert isinstance(decoded, ReadHoldingRegistersResponse)
    assert decoded.registers == [1, 2, 3]


def test_read_coils_roundtrip():
    """ReadCoilsRequest/Response round-trip."""
    req = ReadCoilsRequest(address=10, count=5)
    raw = req.encode_frame()
    decoded = decode_pdu(raw, server=True)
    assert isinstance(decoded, ReadCoilsRequest)
    assert decoded.address == 10
    assert decoded.count == 5

    resp = ReadCoilsResponse(bits=[True, False, True, False, True])
    raw = resp.encode_frame()
    decoded = decode_pdu(raw, server=False)
    assert isinstance(decoded, ReadCoilsResponse)
    # The response decodes all bits in the packed bytes (8 per byte);
    # truncate to the originally requested count.
    assert decoded.bits[:5] == [True, False, True, False, True]


def test_read_discrete_inputs_roundtrip():
    """ReadDiscreteInputsRequest/Response round-trip."""
    req = ReadDiscreteInputsRequest(address=20, count=3)
    raw = req.encode_frame()
    decoded = decode_pdu(raw, server=True)
    assert isinstance(decoded, ReadDiscreteInputsRequest)
    assert decoded.address == 20
    assert decoded.count == 3

    resp = ReadDiscreteInputsResponse(bits=[True, False, True])
    raw = resp.encode_frame()
    decoded = decode_pdu(raw, server=False)
    assert isinstance(decoded, ReadDiscreteInputsResponse)
    assert decoded.bits[:3] == [True, False, True]


def test_read_input_registers_roundtrip():
    """ReadInputRegistersRequest/Response round-trip."""
    req = ReadInputRegistersRequest(address=30, count=4)
    raw = req.encode_frame()
    decoded = decode_pdu(raw, server=True)
    assert isinstance(decoded, ReadInputRegistersRequest)
    assert decoded.address == 30
    assert decoded.count == 4

    resp = ReadInputRegistersResponse(registers=[10, 20, 30, 40])
    raw = resp.encode_frame()
    decoded = decode_pdu(raw, server=False)
    assert isinstance(decoded, ReadInputRegistersResponse)
    assert decoded.registers == [10, 20, 30, 40]


def test_write_single_coil_roundtrip():
    """WriteSingleCoilRequest/Response round-trip."""
    req = WriteSingleCoilRequest(address=10, bits=[True])
    raw = req.encode_frame()
    assert raw[0] == 5
    decoded = decode_pdu(raw, server=True)
    assert isinstance(decoded, WriteSingleCoilRequest)
    assert decoded.address == 10
    assert decoded.value is True

    resp = WriteSingleCoilResponse(address=10, bits=[True])
    raw = resp.encode_frame()
    decoded = decode_pdu(raw, server=False)
    assert isinstance(decoded, WriteSingleCoilResponse)
    assert decoded.address == 10
    assert decoded.value is True


def test_write_single_register_roundtrip():
    """WriteSingleRegisterRequest/Response round-trip."""
    req = WriteSingleRegisterRequest(address=10, registers=[42])
    raw = req.encode_frame()
    assert raw[0] == 6
    decoded = decode_pdu(raw, server=True)
    assert isinstance(decoded, WriteSingleRegisterRequest)
    assert decoded.address == 10
    assert decoded.registers == [42]

    resp = WriteSingleRegisterResponse(address=10, registers=[42])
    raw = resp.encode_frame()
    decoded = decode_pdu(raw, server=False)
    assert isinstance(decoded, WriteSingleRegisterResponse)
    assert decoded.address == 10
    assert decoded.registers == [42]


def test_write_multiple_coils_roundtrip():
    """WriteMultipleCoilsRequest/Response round-trip."""
    req = WriteMultipleCoilsRequest(address=10, bits=[True, False, True])
    raw = req.encode_frame()
    assert raw[0] == 15
    decoded = decode_pdu(raw, server=True)
    assert isinstance(decoded, WriteMultipleCoilsRequest)
    assert decoded.address == 10
    assert decoded.count == 3
    assert decoded.bits == [True, False, True]

    resp = WriteMultipleCoilsResponse(address=10, count=3)
    raw = resp.encode_frame()
    decoded = decode_pdu(raw, server=False)
    assert isinstance(decoded, WriteMultipleCoilsResponse)
    assert decoded.address == 10
    assert decoded.count == 3


def test_write_multiple_registers_roundtrip():
    """WriteMultipleRegistersRequest/Response round-trip."""
    req = WriteMultipleRegistersRequest(address=10, registers=[1, 2, 3])
    raw = req.encode_frame()
    assert raw[0] == 16
    decoded = decode_pdu(raw, server=True)
    assert isinstance(decoded, WriteMultipleRegistersRequest)
    assert decoded.address == 10
    assert decoded.count == 3
    assert decoded.registers == [1, 2, 3]

    resp = WriteMultipleRegistersResponse(address=10, count=3)
    raw = resp.encode_frame()
    decoded = decode_pdu(raw, server=False)
    assert isinstance(decoded, WriteMultipleRegistersResponse)
    assert decoded.address == 10
    assert decoded.count == 3


# --------------------------------------------------------------------------- #
# ExceptionResponse tests
# --------------------------------------------------------------------------- #


def test_exception_response_encode():
    """ExceptionResponse encodes as [FC|0x80, code]."""
    exc = ExceptionResponse(function_code=3, exception_code=ExcCodes.ILLEGAL_DATA_ADDRESS)
    raw = exc.encode_frame()
    assert raw == bytes([0x83, 2])


def test_exception_response_decode():
    """ExceptionResponse decodes from [FC|0x80, code]."""
    raw = bytes([0x83, 2])
    decoded = decode_pdu(raw, server=False)
    assert isinstance(decoded, ExceptionResponse)
    assert decoded.function_code == 3
    assert decoded.exception_code == 2
    assert decoded.isError()


def test_exception_response_is_error():
    """isError() returns True only for ExceptionResponse."""
    exc = ExceptionResponse(3, 4)
    assert exc.isError()
    resp = ReadHoldingRegistersResponse(registers=[1])
    assert not resp.isError()


# --------------------------------------------------------------------------- #
# decode_pdu role-asymmetry tests
# --------------------------------------------------------------------------- #


def test_decode_pdu_role_asymmetry():
    """A request FC byte decodes as request (server) or response (client)."""
    # FC=3 with request payload (addr+count)
    raw = bytes([3]) + struct.pack(">HH", 100, 5)
    req = decode_pdu(raw, server=True)
    assert isinstance(req, ReadHoldingRegistersRequest)
    assert req.address == 100
    assert req.count == 5

    # Same FC=3 but with response payload (byte_count+registers)
    raw = bytes([3, 6, 0, 1, 0, 2, 0, 3])
    resp = decode_pdu(raw, server=False)
    assert isinstance(resp, ReadHoldingRegistersResponse)
    assert resp.registers == [1, 2, 3]


def test_decode_pdu_unknown_fc():
    """Unknown function code raises ModbusIOError."""
    try:
        decode_pdu(bytes([99]), server=True)
        raise AssertionError("should have raised")
    except ModbusIOError:
        pass


def test_decode_pdu_empty():
    """Empty data raises ModbusIOError."""
    try:
        decode_pdu(b"", server=True)
        raise AssertionError("should have raised")
    except ModbusIOError:
        pass


# --------------------------------------------------------------------------- #
# Request.execute tests
# --------------------------------------------------------------------------- #


def test_execute_read_holding_registers():
    """Request.execute returns the expected response for a read."""
    ctx = FakeContext()
    ctx.data["h"][100] = 42
    ctx.data["h"][101] = 99

    req = ReadHoldingRegistersRequest(address=100, count=2)
    resp = req.execute(ctx)
    assert isinstance(resp, ReadHoldingRegistersResponse)
    assert resp.registers == [42, 99]


def test_execute_read_coils():
    """Request.execute returns the expected response for a coil read."""
    ctx = FakeContext()
    ctx.data["c"][10] = 1
    ctx.data["c"][11] = 0
    ctx.data["c"][12] = 1

    req = ReadCoilsRequest(address=10, count=3)
    resp = req.execute(ctx)
    assert isinstance(resp, ReadCoilsResponse)
    assert resp.bits == [True, False, True]


def test_execute_illegal_address():
    """Out-of-range address yields ExceptionResponse with ILLEGAL_DATA_ADDRESS."""
    ctx = FakeContext()

    req = ReadHoldingRegistersRequest(address=100, count=1)
    resp = req.execute(ctx)
    assert isinstance(resp, ExceptionResponse)
    assert resp.exception_code == ExcCodes.ILLEGAL_DATA_ADDRESS


def test_execute_write_single_register():
    """WriteSingleRegister.execute mutates the context."""
    ctx = FakeContext()

    req = WriteSingleRegisterRequest(address=50, registers=[77])
    resp = req.execute(ctx)
    assert isinstance(resp, WriteSingleRegisterResponse)
    assert resp.address == 50
    assert resp.registers == [77]
    assert ctx.data["h"][50] == 77


def test_execute_write_multiple_registers():
    """WriteMultipleRegisters.execute mutates the context."""
    ctx = FakeContext()

    req = WriteMultipleRegistersRequest(address=60, registers=[1, 2, 3])
    resp = req.execute(ctx)
    assert isinstance(resp, WriteMultipleRegistersResponse)
    assert resp.address == 60
    assert resp.count == 3
    assert ctx.data["h"][60] == 1
    assert ctx.data["h"][61] == 2
    assert ctx.data["h"][62] == 3


def test_execute_write_single_coil():
    """WriteSingleCoil.execute mutates the context."""
    ctx = FakeContext()

    req = WriteSingleCoilRequest(address=20, bits=[True])
    resp = req.execute(ctx)
    assert isinstance(resp, WriteSingleCoilResponse)
    assert resp.address == 20
    assert resp.value is True
    assert ctx.data["c"][20] == 1


def test_execute_write_multiple_coils():
    """WriteMultipleCoils.execute mutates the context."""
    ctx = FakeContext()

    req = WriteMultipleCoilsRequest(address=30, bits=[True, False, True])
    resp = req.execute(ctx)
    assert isinstance(resp, WriteMultipleCoilsResponse)
    assert resp.address == 30
    assert resp.count == 3
    assert ctx.data["c"][30] == 1
    assert ctx.data["c"][31] == 0
    assert ctx.data["c"][32] == 1


def test_execute_free_function():
    """execute_request() works the same as Request.execute()."""
    ctx = FakeContext()
    ctx.data["h"][100] = 42

    req = ReadHoldingRegistersRequest(address=100, count=1)
    resp = execute_request(req, ctx)
    assert isinstance(resp, ReadHoldingRegistersResponse)
    assert resp.registers == [42]
