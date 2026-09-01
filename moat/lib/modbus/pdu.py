"""
Modbus PDU definitions.

Defines a :class:`PDU` base and request/response classes for function
codes 1, 2, 3, 4, 5, 6, 15, 16, plus :class:`ExceptionResponse`.

Each class has a class attribute :attr:`PDU.function_code`, an
:meth:`PDU.encode` method returning the payload bytes (after the FC
byte), a :meth:`PDU.decode` method populating from payload bytes, and
an :meth:`PDU.isError` method (True only for :class:`ExceptionResponse`).

``transaction_id`` and ``unit_id`` are plain mutable attributes stamped
onto the parsed object by the framer.

The role-aware free function :func:`decode_pdu` reads the leading FC
byte and instantiates the request class (when ``server=True``) or
response class (when ``server=False``); an unknown FC raises
:class:`~moat.lib.modbus.errors.ModbusIOError`.

Each ``Request`` defines ``execute`` operating against a
:class:`Context` :class:`typing.Protocol` with per-kind
``get_values(addr, count)`` and ``set_values(addr, values)``.
Illegal-address/value conditions yield an :class:`ExceptionResponse`
with the right :class:`~moat.lib.modbus.errors.ExcCodes`.
"""

from __future__ import annotations

import struct

from .errors import ExcCodes, ModbusIOError

import typing
from typing import Protocol


class Context(Protocol):
    """Minimal datastore protocol consumed by ``Request.execute``.

    The four kinds map to Modbus data types:
    ``"c"`` = coils, ``"d"`` = discrete inputs,
    ``"h"`` = holding registers, ``"i"`` = input registers.
    """

    def get_values(self, kind: str, address: int, count: int) -> list[int]:
        """Return *count* values starting at *address* for data kind *kind*.

        Raises :class:`KeyError` if the address range is not available.
        """
        ...

    def set_values(self, kind: str, address: int, values: list[int]) -> None:
        """Set *values* starting at *address* for data kind *kind*.

        Raises :class:`KeyError` if the address range is not available.
        """
        ...


class PDU:
    """Base class for all Modbus PDUs."""

    function_code: int = 0
    """The Modbus function code (class attribute)."""

    transaction_id: int = 0
    """Set by the framer from the MBAP header (TCP)."""

    unit_id: int = 0
    """Set by the framer from the MBAP header or RTU address."""

    def encode(self) -> bytes:
        """Return the payload bytes after the function-code byte."""
        raise NotImplementedError

    def decode(self, data: bytes) -> None:
        """Populate self from payload bytes (after the FC byte)."""
        raise NotImplementedError

    def isError(self) -> bool:
        """Return True if this is an exception response."""
        return False

    def encode_frame(self) -> bytes:
        """Return the full PDU bytes including the function-code byte."""
        return bytes([self.function_code]) + self.encode()


class ExceptionResponse(PDU):
    """Modbus exception response.

    Encodes as ``[FC | 0x80, exception_code]``.
    """

    def __init__(self, function_code: int = 0, exception_code: int = 0) -> None:
        self.function_code = function_code
        self.exception_code = exception_code

    def encode(self) -> bytes:
        """Return the exception-code byte."""
        return bytes([self.exception_code])

    def decode(self, data: bytes) -> None:
        """Populate from payload bytes."""
        if len(data) < 1:
            raise ModbusIOError("ExceptionResponse: empty payload")
        self.exception_code = data[0]

    def isError(self) -> bool:
        """Always ``True`` for an exception response."""
        return True

    def encode_frame(self) -> bytes:
        """Return the full PDU bytes including the function-code byte.

        For an exception response the wire byte is ``FC | 0x80``.
        """
        return bytes([self.function_code | 0x80]) + self.encode()

    def __repr__(self) -> str:
        return f"ExceptionResponse(fc={self.function_code}, code={self.exception_code})"


class _Request(PDU):
    """Base class for request PDUs.

    Provides the :meth:`execute` entry point used by servers to process
    an incoming request against a :class:`Context`.
    """

    def execute(self, ctx: Context) -> PDU:
        """Execute this request against *ctx* and return the response PDU."""
        return execute_request(self, ctx)


# --------------------------------------------------------------------------- #
# Bit (coil / discrete-input) PDUs
# --------------------------------------------------------------------------- #


class _BitReadRequest(_Request):
    """Base for read-coils / read-discrete-inputs requests."""

    def __init__(
        self,
        *,
        address: int = 0,
        count: int = 0,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.address = address
        self.count = count
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    def encode(self) -> bytes:
        return struct.pack(">HH", self.address, self.count)

    def decode(self, data: bytes) -> None:
        if len(data) < 4:
            raise ModbusIOError("BitReadRequest: short payload")
        self.address, self.count = struct.unpack(">HH", data[:4])


class _BitReadResponse(PDU):
    """Base for read-coils / read-discrete-inputs responses."""

    def __init__(
        self,
        *,
        bits: list[bool] | None = None,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.bits: list[bool] = bits or []
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    @property
    def registers(self) -> list[int]:
        """Compatibility: expose bits as integers via ``registers``."""
        return [int(b) for b in self.bits]

    def encode(self) -> bytes:
        byte_count = (len(self.bits) + 7) // 8
        packed = bytearray(byte_count)
        for i, bit in enumerate(self.bits):
            if bit:
                packed[i // 8] |= 1 << (i % 8)
        return bytes([byte_count]) + bytes(packed)

    def decode(self, data: bytes) -> None:
        if len(data) < 1:
            raise ModbusIOError("BitReadResponse: empty payload")
        byte_count = data[0]
        if len(data) < 1 + byte_count:
            raise ModbusIOError("BitReadResponse: short payload")
        # Decode all bits from the packed bytes.  The trailing padding
        # bits (beyond the requested count) are included; callers that
        # know the expected count should truncate.
        bits: list[bool] = []
        for i in range(byte_count * 8):
            bits.append(bool(data[1 + i // 8] & (1 << (i % 8))))
        self.bits = bits


class ReadCoilsRequest(_BitReadRequest):
    """FC 1: Read Coils."""

    function_code = 1


class ReadCoilsResponse(_BitReadResponse):
    """FC 1: Read Coils response."""

    function_code = 1


class ReadDiscreteInputsRequest(_BitReadRequest):
    """FC 2: Read Discrete Inputs."""

    function_code = 2


class ReadDiscreteInputsResponse(_BitReadResponse):
    """FC 2: Read Discrete Inputs response."""

    function_code = 2


# --------------------------------------------------------------------------- #
# Register (holding / input) PDUs
# --------------------------------------------------------------------------- #


class _RegReadRequest(_Request):
    """Base for read-holding / read-input register requests."""

    def __init__(
        self,
        *,
        address: int = 0,
        count: int = 0,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.address = address
        self.count = count
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    def encode(self) -> bytes:
        return struct.pack(">HH", self.address, self.count)

    def decode(self, data: bytes) -> None:
        if len(data) < 4:
            raise ModbusIOError("RegReadRequest: short payload")
        self.address, self.count = struct.unpack(">HH", data[:4])


class _RegReadResponse(PDU):
    """Base for read-holding / read-input register responses."""

    def __init__(
        self,
        *,
        registers: list[int] | None = None,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.registers: list[int] = registers or []
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    @property
    def bits(self) -> list[bool]:
        """Compatibility: expose registers as booleans via ``bits``."""
        return [bool(r) for r in self.registers]

    def encode(self) -> bytes:
        byte_count = len(self.registers) * 2
        return struct.pack(">B" + "H" * len(self.registers), byte_count, *self.registers)

    def decode(self, data: bytes) -> None:
        if len(data) < 1:
            raise ModbusIOError("RegReadResponse: empty payload")
        byte_count = data[0]
        n_regs = byte_count // 2
        if len(data) < 1 + byte_count:
            raise ModbusIOError("RegReadResponse: short payload")
        self.registers = list(struct.unpack(">" + "H" * n_regs, data[1 : 1 + byte_count]))


class ReadHoldingRegistersRequest(_RegReadRequest):
    """FC 3: Read Holding Registers."""

    function_code = 3


class ReadHoldingRegistersResponse(_RegReadResponse):
    """FC 3: Read Holding Registers response."""

    function_code = 3


class ReadInputRegistersRequest(_RegReadRequest):
    """FC 4: Read Input Registers."""

    function_code = 4


class ReadInputRegistersResponse(_RegReadResponse):
    """FC 4: Read Input Registers response."""

    function_code = 4


# --------------------------------------------------------------------------- #
# Write-single PDUs
# --------------------------------------------------------------------------- #


class WriteSingleCoilRequest(_Request):
    """FC 5: Write Single Coil.

    On the wire: ``[address_hi, address_lo, value_hi, value_lo]`` where
    value is ``0xFF00`` for ON and ``0x0000`` for OFF.
    """

    function_code = 5

    def __init__(
        self,
        *,
        address: int = 0,
        bits: list[bool] | None = None,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.address = address
        self.bits: list[bool] = bits or []
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    @property
    def value(self) -> bool:
        """The coil value."""
        return bool(self.bits) and self.bits[0]

    def encode(self) -> bytes:
        """Return the payload bytes after the function-code byte."""
        v = 0xFF00 if self.value else 0x0000
        return struct.pack(">HH", self.address, v)

    def decode(self, data: bytes) -> None:
        """Populate self from payload bytes (after the FC byte)."""
        if len(data) < 4:
            raise ModbusIOError("WriteSingleCoilRequest: short payload")
        self.address, v = struct.unpack(">HH", data[:4])
        self.bits = [v == 0xFF00]


class WriteSingleCoilResponse(PDU):
    """FC 5: Write Single Coil response (echoes the request)."""

    function_code = 5

    def __init__(
        self,
        *,
        address: int = 0,
        bits: list[bool] | None = None,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.address = address
        self.bits: list[bool] = bits or []
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    @property
    def value(self) -> bool:
        """The coil value."""
        return bool(self.bits) and self.bits[0]

    def encode(self) -> bytes:
        """Return the payload bytes after the function-code byte."""
        v = 0xFF00 if self.value else 0x0000
        return struct.pack(">HH", self.address, v)

    def decode(self, data: bytes) -> None:
        """Populate self from payload bytes (after the FC byte)."""
        if len(data) < 4:
            raise ModbusIOError("WriteSingleCoilResponse: short payload")
        self.address, v = struct.unpack(">HH", data[:4])
        self.bits = [v == 0xFF00]


class WriteSingleRegisterRequest(_Request):
    """FC 6: Write Single Register.

    On the wire: ``[address_hi, address_lo, value_hi, value_lo]``.
    """

    function_code = 6

    def __init__(
        self,
        *,
        address: int = 0,
        registers: list[int] | None = None,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.address = address
        self.registers: list[int] = registers or []
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    @property
    def value(self) -> int:
        """The register value."""
        return self.registers[0] if self.registers else 0

    def encode(self) -> bytes:
        """Return the payload bytes after the function-code byte."""
        v = self.registers[0] if self.registers else 0
        return struct.pack(">HH", self.address, v)

    def decode(self, data: bytes) -> None:
        """Populate self from payload bytes (after the FC byte)."""
        if len(data) < 4:
            raise ModbusIOError("WriteSingleRegisterRequest: short payload")
        self.address, v = struct.unpack(">HH", data[:4])
        self.registers = [v]


class WriteSingleRegisterResponse(PDU):
    """FC 6: Write Single Register response (echoes the request)."""

    function_code = 6

    def __init__(
        self,
        *,
        address: int = 0,
        registers: list[int] | None = None,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.address = address
        self.registers: list[int] = registers or []
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    @property
    def value(self) -> int:
        """The register value."""
        return self.registers[0] if self.registers else 0

    def encode(self) -> bytes:
        """Return the payload bytes after the function-code byte."""
        v = self.registers[0] if self.registers else 0
        return struct.pack(">HH", self.address, v)

    def decode(self, data: bytes) -> None:
        """Populate self from payload bytes (after the FC byte)."""
        if len(data) < 4:
            raise ModbusIOError("WriteSingleRegisterResponse: short payload")
        self.address, v = struct.unpack(">HH", data[:4])
        self.registers = [v]


# --------------------------------------------------------------------------- #
# Write-multiple PDUs
# --------------------------------------------------------------------------- #


class WriteMultipleCoilsRequest(_Request):
    """FC 15: Write Multiple Coils.

    On the wire: ``[addr_hi, addr_lo, count_hi, count_lo, byte_count,
    data_bytes...]``.
    """

    function_code = 15

    def __init__(
        self,
        *,
        address: int = 0,
        bits: list[bool] | None = None,
        count: int | None = None,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.address = address
        self.bits: list[bool] = bits or []
        self.count = count if count is not None else len(self.bits)
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    def encode(self) -> bytes:
        """Return the payload bytes after the function-code byte."""
        byte_count = (len(self.bits) + 7) // 8
        packed = bytearray(byte_count)
        for i, bit in enumerate(self.bits):
            if bit:
                packed[i // 8] |= 1 << (i % 8)
        return struct.pack(">HHB", self.address, self.count, byte_count) + bytes(packed)

    def decode(self, data: bytes) -> None:
        """Populate self from payload bytes (after the FC byte)."""
        if len(data) < 5:
            raise ModbusIOError("WriteMultipleCoilsRequest: short payload")
        self.address, self.count, byte_count = struct.unpack(">HHB", data[:5])
        if len(data) < 5 + byte_count:
            raise ModbusIOError("WriteMultipleCoilsRequest: short payload")
        bits: list[bool] = []
        for i in range(self.count):
            bits.append(bool(data[5 + i // 8] & (1 << (i % 8))))
        self.bits = bits


class WriteMultipleCoilsResponse(PDU):
    """FC 15: Write Multiple Coils response.

    On the wire: ``[addr_hi, addr_lo, count_hi, count_lo]``.
    """

    function_code = 15

    def __init__(
        self,
        *,
        address: int = 0,
        count: int = 0,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.address = address
        self.count = count
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    def encode(self) -> bytes:
        """Return the payload bytes after the function-code byte."""
        return struct.pack(">HH", self.address, self.count)

    def decode(self, data: bytes) -> None:
        """Populate self from payload bytes (after the FC byte)."""
        if len(data) < 4:
            raise ModbusIOError("WriteMultipleCoilsResponse: short payload")
        self.address, self.count = struct.unpack(">HH", data[:4])


class WriteMultipleRegistersRequest(_Request):
    """FC 16: Write Multiple Registers.

    On the wire: ``[addr_hi, addr_lo, count_hi, count_lo, byte_count,
    reg_bytes...]``.
    """

    function_code = 16

    def __init__(
        self,
        *,
        address: int = 0,
        registers: list[int] | None = None,
        count: int | None = None,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.address = address
        self.registers: list[int] = registers or []
        self.count = count if count is not None else len(self.registers)
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    def encode(self) -> bytes:
        """Return the payload bytes after the function-code byte."""
        byte_count = len(self.registers) * 2
        return struct.pack(
            ">HHB" + "H" * len(self.registers),
            self.address,
            self.count,
            byte_count,
            *self.registers,
        )

    def decode(self, data: bytes) -> None:
        """Populate self from payload bytes (after the FC byte)."""
        if len(data) < 5:
            raise ModbusIOError("WriteMultipleRegistersRequest: short payload")
        self.address, self.count, byte_count = struct.unpack(">HHB", data[:5])
        n_regs = byte_count // 2
        if len(data) < 5 + byte_count:
            raise ModbusIOError("WriteMultipleRegistersRequest: short payload")
        self.registers = list(struct.unpack(">" + "H" * n_regs, data[5 : 5 + byte_count]))


class WriteMultipleRegistersResponse(PDU):
    """FC 16: Write Multiple Registers response.

    On the wire: ``[addr_hi, addr_lo, count_hi, count_lo]``.
    """

    function_code = 16

    def __init__(
        self,
        *,
        address: int = 0,
        count: int = 0,
        unit_id: int = 0,
        transaction_id: int = 0,
    ) -> None:
        self.address = address
        self.count = count
        self.unit_id = unit_id
        self.transaction_id = transaction_id

    def encode(self) -> bytes:
        """Return the payload bytes after the function-code byte."""
        return struct.pack(">HH", self.address, self.count)

    def decode(self, data: bytes) -> None:
        """Populate self from payload bytes (after the FC byte)."""
        if len(data) < 4:
            raise ModbusIOError("WriteMultipleRegistersResponse: short payload")
        self.address, self.count = struct.unpack(">HH", data[:4])


# --------------------------------------------------------------------------- #
# Class registries for decode_pdu
# --------------------------------------------------------------------------- #

_REQUEST_CLASSES: dict[int, type[PDU]] = {
    1: ReadCoilsRequest,
    2: ReadDiscreteInputsRequest,
    3: ReadHoldingRegistersRequest,
    4: ReadInputRegistersRequest,
    5: WriteSingleCoilRequest,
    6: WriteSingleRegisterRequest,
    15: WriteMultipleCoilsRequest,
    16: WriteMultipleRegistersRequest,
}

_RESPONSE_CLASSES: dict[int, type[PDU]] = {
    1: ReadCoilsResponse,
    2: ReadDiscreteInputsResponse,
    3: ReadHoldingRegistersResponse,
    4: ReadInputRegistersResponse,
    5: WriteSingleCoilResponse,
    6: WriteSingleRegisterResponse,
    15: WriteMultipleCoilsResponse,
    16: WriteMultipleRegistersResponse,
}


# --------------------------------------------------------------------------- #
# Request.execute — owned dispatch against a Context
# --------------------------------------------------------------------------- #

# Maps function code -> data-store kind for read requests.
_FC_READ_KIND: dict[int, str] = {
    1: "c",
    2: "d",
    3: "h",
    4: "i",
}

# Function code -> response class for the read executors.
_BIT_READ_RESP: dict[int, type[_BitReadResponse]] = {
    1: ReadCoilsResponse,
    2: ReadDiscreteInputsResponse,
}
_REG_READ_RESP: dict[int, type[_RegReadResponse]] = {
    3: ReadHoldingRegistersResponse,
    4: ReadInputRegistersResponse,
}


def _execute_bit_read(req: _BitReadRequest, ctx: Context) -> PDU:
    kind = _FC_READ_KIND[req.function_code]
    try:
        vals = ctx.get_values(kind, req.address, req.count)
    except KeyError:
        return ExceptionResponse(req.function_code, ExcCodes.ILLEGAL_DATA_ADDRESS)
    bits = [bool(v) if v is not None else False for v in vals[: req.count]]
    resp = _BIT_READ_RESP[req.function_code](bits=bits)
    resp.unit_id = req.unit_id
    resp.transaction_id = req.transaction_id
    return resp


def _execute_reg_read(req: _RegReadRequest, ctx: Context) -> PDU:
    kind = _FC_READ_KIND[req.function_code]
    try:
        vals = ctx.get_values(kind, req.address, req.count)
    except KeyError:
        return ExceptionResponse(req.function_code, ExcCodes.ILLEGAL_DATA_ADDRESS)
    regs = [int(v) if v is not None else 0 for v in vals[: req.count]]
    resp = _REG_READ_RESP[req.function_code](registers=regs)
    resp.unit_id = req.unit_id
    resp.transaction_id = req.transaction_id
    return resp


def _execute_write_single_coil(req: WriteSingleCoilRequest, ctx: Context) -> PDU:
    try:
        ctx.set_values("c", req.address, [1 if req.value else 0])
    except KeyError:
        return ExceptionResponse(req.function_code, ExcCodes.ILLEGAL_DATA_ADDRESS)
    resp = WriteSingleCoilResponse(address=req.address, bits=req.bits)
    resp.unit_id = req.unit_id
    resp.transaction_id = req.transaction_id
    return resp


def _execute_write_single_register(req: WriteSingleRegisterRequest, ctx: Context) -> PDU:
    try:
        ctx.set_values("h", req.address, req.registers)
    except KeyError:
        return ExceptionResponse(req.function_code, ExcCodes.ILLEGAL_DATA_ADDRESS)
    resp = WriteSingleRegisterResponse(address=req.address, registers=req.registers)
    resp.unit_id = req.unit_id
    resp.transaction_id = req.transaction_id
    return resp


def _execute_write_multiple_coils(req: WriteMultipleCoilsRequest, ctx: Context) -> PDU:
    try:
        ctx.set_values("c", req.address, [1 if b else 0 for b in req.bits])
    except KeyError:
        return ExceptionResponse(req.function_code, ExcCodes.ILLEGAL_DATA_ADDRESS)
    resp = WriteMultipleCoilsResponse(address=req.address, count=req.count)
    resp.unit_id = req.unit_id
    resp.transaction_id = req.transaction_id
    return resp


def _execute_write_multiple_registers(req: WriteMultipleRegistersRequest, ctx: Context) -> PDU:
    try:
        ctx.set_values("h", req.address, req.registers)
    except KeyError:
        return ExceptionResponse(req.function_code, ExcCodes.ILLEGAL_DATA_ADDRESS)
    resp = WriteMultipleRegistersResponse(address=req.address, count=req.count)
    resp.unit_id = req.unit_id
    resp.transaction_id = req.transaction_id
    return resp


_EXECUTE_MAP: dict[int, typing.Callable[..., PDU]] = {
    1: _execute_bit_read,
    2: _execute_bit_read,
    3: _execute_reg_read,
    4: _execute_reg_read,
    5: _execute_write_single_coil,
    6: _execute_write_single_register,
    15: _execute_write_multiple_coils,
    16: _execute_write_multiple_registers,
}


def execute_request(req: PDU, ctx: Context) -> PDU:
    """Execute a request PDU against a :class:`Context`.

    Returns the matching response PDU, or an :class:`ExceptionResponse`
    on illegal address/value.
    """
    fn = _EXECUTE_MAP.get(req.function_code)
    if fn is None:
        return ExceptionResponse(req.function_code, ExcCodes.ILLEGAL_FUNCTION)
    return fn(req, ctx)


def decode_pdu(data: bytes, *, server: bool) -> PDU:
    """Decode a PDU from raw bytes (including the leading FC byte).

    Args:
        data: Raw PDU bytes.  The first byte is the function code;
              for exception responses it is ``FC | 0x80``.
        server: If True, decode as a **request** (incoming on a server);
               if False, decode as a **response** (incoming on a client).

    Returns:
        The decoded PDU object.

    Raises:
        ModbusIOError: If the function code is unknown.
    """
    if not data:
        raise ModbusIOError("decode_pdu: empty data")

    fc = data[0]

    # Exception response: FC | 0x80
    if fc & 0x80:
        exc = ExceptionResponse()
        exc.function_code = fc & 0x7F
        exc.decode(data[1:])
        return exc

    table = _REQUEST_CLASSES if server else _RESPONSE_CLASSES
    cls = table.get(fc)
    if cls is None:
        raise ModbusIOError(f"decode_pdu: unknown function code {fc}")

    obj = cls()
    obj.decode(data[1:])
    return obj
