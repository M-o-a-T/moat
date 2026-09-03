"""
CRC-16/Modbus checksum.

Implements :func:`crc16` per the Modbus specification: polynomial
``0xA001`` (bit-reversed ``0x8005``), init ``0xFFFF``, no final XOR,
LSB-first processing, byte-wise loop (no lookup table).

The CRC is appended to RTU frames as two bytes, low byte first.
"""

from __future__ import annotations


def crc16(data: bytes) -> int:
    """Compute the CRC-16/Modbus checksum of *data*.

    Args:
        data: The bytes to checksum.

    Returns:
        The 16-bit CRC value (0--65535).

    The algorithm uses polynomial ``0xA001`` (reverse of ``0x8005``),
    initial value ``0xFFFF``, and no final XOR.  Bytes are processed
    LSB-first.  The result is emitted low byte first when appended to
    a frame.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF
