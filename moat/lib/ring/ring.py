"""
Characer-based ring buffer.
"""

from __future__ import annotations


class RingBuffer:
    """
    This ring buffer can hold a predetermined number of bytes.

    Old data are overwritten when the reader doesn't keep up.
    """

    def __init__(self, length: int):
        """
        Sets up a ring buffer of size `len` (i.e. holds zero to len-1 bytes).
        """
        self._buf = bytearray(length)
        self._read_pos = 0  # Position to read from
        self._count = 0  # Number of bytes available

    def write(self, buf: bytes) -> None:
        """
        Adds the bytes in `buf` to the end of the buffer.

        If the buffer is full, discards as many old bytes as necessary and
        replaces the first byte with a 0x00.
        """
        if not buf:
            return

        buf_len = len(self._buf)
        write_len = len(buf)

        # If writing more than buffer can hold, only write last buf_len bytes
        if write_len > buf_len:
            buf = memoryview(buf)[write_len - buf_len :]
            write_len = buf_len

        # Check if we'll overflow
        overflow = max(0, self._count + write_len - buf_len)
        if overflow > 0:
            # Advance read position to discard old bytes
            self._read_pos = (self._read_pos + overflow) % buf_len
            self._count -= overflow

        # Write data, handling wraparound
        write_pos = (self._read_pos + self._count) % buf_len
        space_to_end = buf_len - write_pos
        if write_len <= space_to_end:
            # Simple case: no wraparound
            self._buf[write_pos : write_pos + write_len] = buf
        else:
            # Wraparound case: split the write
            self._buf[write_pos:buf_len] = buf[:space_to_end]
            self._buf[0 : write_len - space_to_end] = buf[space_to_end:]

        self._count += write_len

        # Replace the oldest byte with 0x00 if we had overflow
        if overflow > 0:
            self._buf[self._read_pos] = 0x00

    def readinto(self, buf: bytearray) -> int:
        """
        Copies as many bytes as will fit (or are available, whichever is
        smaller) into the buffer and advance the read counter.
        """
        read_len = min(len(buf), self._count)
        if read_len == 0:
            return 0

        buf_len = len(self._buf)
        space_to_end = buf_len - self._read_pos

        if read_len <= space_to_end:
            # Simple case: no wraparound
            buf[:read_len] = self._buf[self._read_pos : self._read_pos + read_len]
        else:
            # Wraparound case: split the read
            buf[:space_to_end] = self._buf[self._read_pos : buf_len]
            buf[space_to_end:read_len] = self._buf[0 : read_len - space_to_end]

        self._read_pos = (self._read_pos + read_len) % buf_len
        self._count -= read_len
        return read_len

    def any(self) -> int:
        """
        Returns the number of bytes in the buffer.
        """
        return self._count
