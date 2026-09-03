"""
Modbus exception codes and I/O error.

Defines :class:`ExcCodes` as an :class:`enum.IntEnum` covering the
standard Modbus exception codes, plus two source-compatibility
aliases used by the legacy ``moat.modbus`` code, and
:class:`ModbusIOError` replacing pymodbus'
``pymodbus.exceptions.ModbusIOException``.
"""

from __future__ import annotations

import enum


class ExcCodes(enum.IntEnum):
    """Standard Modbus exception codes.

    The aliases :attr:`DEVICE_FAILURE` and :attr:`GATEWAY_NO_RESPONSE`
    are kept for source compatibility with the old ``moat.modbus`` code
    that referenced pymodbus' ``ExcCodes.DEVICE_FAILURE`` /
    ``ExcCodes.GATEWAY_NO_RESPONSE``.
    """

    ILLEGAL_FUNCTION = 1
    ILLEGAL_DATA_ADDRESS = 2
    ILLEGAL_DATA_VALUE = 3
    SERVER_DEVICE_FAILURE = 4
    ACKNOWLEDGE = 5
    SERVER_DEVICE_BUSY = 6
    NEGATIVE_ACKNOWLEDGE = 7
    MEMORY_PARITY_ERROR = 8
    GATEWAY_PATH_UNAVAILABLE = 10
    GATEWAY_TARGET_NO_RESPONSE = 11

    # Source-compatibility aliases.
    DEVICE_FAILURE = 4
    """Alias for :attr:`~ExcCodes.SERVER_DEVICE_FAILURE`."""

    GATEWAY_NO_RESPONSE = 11
    """Alias for :attr:`~ExcCodes.GATEWAY_TARGET_NO_RESPONSE`."""


class ModbusIOError(Exception):
    """Generic Modbus I/O error.

    Replaces pymodbus' ``ModbusIOException``.  Raised when a frame
    cannot be decoded or a protocol violation is detected.
    """
