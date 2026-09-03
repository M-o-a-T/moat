"""
Sans-IO Modbus protocol core.

This library implements the minimal Modbus protocol subset used by
``moat.modbus`` -- PDU encoding/decoding for function codes 1, 2, 3,
4, 5, 6, 15, 16, plus TCP (MBAP) and RTU framers with a role flag.

It is strictly **sans-IO**: no sockets, no serial ports, no sleeping,
no waiting, no task spawning.  Bytes in -> PDUs out, and vice-versa.
The only mutable state permitted is a framer's internal byte
accumulator.

Stdlib only -- no ``pymodbus``, no ``anyio``.
"""

from __future__ import annotations

from ._crc import crc16
from .errors import ExcCodes, ModbusIOError
from .framer import FramerRTU, FramerTCP
from .pdu import (
    PDU,
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
)

__all__ = [
    "PDU",
    "ExcCodes",
    "ExceptionResponse",
    "FramerRTU",
    "FramerTCP",
    "ModbusIOError",
    "ReadCoilsRequest",
    "ReadCoilsResponse",
    "ReadDiscreteInputsRequest",
    "ReadDiscreteInputsResponse",
    "ReadHoldingRegistersRequest",
    "ReadHoldingRegistersResponse",
    "ReadInputRegistersRequest",
    "ReadInputRegistersResponse",
    "WriteMultipleCoilsRequest",
    "WriteMultipleCoilsResponse",
    "WriteMultipleRegistersRequest",
    "WriteMultipleRegistersResponse",
    "WriteSingleCoilRequest",
    "WriteSingleCoilResponse",
    "WriteSingleRegisterRequest",
    "WriteSingleRegisterResponse",
    "crc16",
    "decode_pdu",
]
