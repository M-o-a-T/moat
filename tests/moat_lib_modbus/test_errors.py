"""Tests for :mod:`moat.lib.modbus.errors`."""

from __future__ import annotations

from moat.lib.modbus.errors import ExcCodes, ModbusIOError


def test_exc_codes_int_values():
    """Standard exception codes have the correct integer values."""
    assert ExcCodes.ILLEGAL_FUNCTION == 1
    assert ExcCodes.ILLEGAL_DATA_ADDRESS == 2
    assert ExcCodes.ILLEGAL_DATA_VALUE == 3
    assert ExcCodes.SERVER_DEVICE_FAILURE == 4
    assert ExcCodes.ACKNOWLEDGE == 5
    assert ExcCodes.SERVER_DEVICE_BUSY == 6
    assert ExcCodes.NEGATIVE_ACKNOWLEDGE == 7
    assert ExcCodes.GATEWAY_PATH_UNAVAILABLE == 10
    assert ExcCodes.GATEWAY_TARGET_NO_RESPONSE == 11


def test_exc_codes_aliases():
    """Source-compatibility aliases map to the canonical members."""
    assert ExcCodes.DEVICE_FAILURE == ExcCodes.SERVER_DEVICE_FAILURE == 4
    assert ExcCodes.GATEWAY_NO_RESPONSE == ExcCodes.GATEWAY_TARGET_NO_RESPONSE == 11


def test_modbus_io_error():
    """ModbusIOError is a subclass of Exception."""
    exc = ModbusIOError("test")
    assert isinstance(exc, Exception)
    assert str(exc) == "test"
