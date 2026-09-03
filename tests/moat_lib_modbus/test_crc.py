"""Tests for :mod:`moat.lib.modbus._crc`."""

from __future__ import annotations

from moat.lib.modbus._crc import crc16


def test_crc_empty():
    """CRC of empty data is the init value 0xFFFF."""
    assert crc16(b"") == 0xFFFF


def test_crc_known_vectors():
    """Known-answer tests for CRC-16/Modbus.

    Vectors verified against pymodbus' own CRC implementation.
    """
    # Read-holding-registers request: addr=1, FC=3, reg=0, count=10
    data = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])
    assert crc16(data) == 0xCDC5

    # Write-single-register response: addr=1, FC=6, reg=0, value=3
    data = bytes([0x01, 0x06, 0x00, 0x00, 0x00, 0x03])
    assert crc16(data) == 0xCBC9

    # Multi-register write request: addr=1, FC=16, reg=0, count=2, bc=4, vals
    data = bytes([0x01, 0x10, 0x00, 0x00, 0x00, 0x02, 0x04, 0x00, 0x01, 0x00, 0x02])
    assert crc16(data) == 0xAE23


def test_crc_round_trip():
    """Appending the CRC and re-scanning validates (CRC of full frame is 0)."""
    payload = bytes([0x01, 0x03, 0x02, 0x12, 0x34])
    c = crc16(payload)
    frame = payload + c.to_bytes(2, "little")
    assert crc16(frame) == 0
