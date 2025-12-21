"""
Tests for the RingBuffer implementation.
"""

from __future__ import annotations

from moat.lib.ring import RingBuffer


class TestRingBufferBasics:
    """Test basic ring buffer operations."""

    def test_initialization(self):
        """Test that buffer initializes correctly."""
        rb = RingBuffer(10)
        assert rb.n_avail == 0
        assert rb.n_free == 10

    def test_simple_write_and_read(self):
        """Test simple write and read without wraparound."""
        rb = RingBuffer(10)
        assert rb.write(b"hello") == 5
        assert rb.n_avail == 5
        assert rb.n_free == 5

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 5
        assert buf[:5] == b"hello"
        assert rb.n_avail == 0
        assert rb.n_free == 10

    def test_multiple_writes_and_reads(self):
        """Test multiple write/read cycles."""
        rb = RingBuffer(10)

        assert rb.write(b"abc") == 3
        assert rb.n_avail == 3

        assert rb.write(b"def") == 3
        assert rb.n_avail == 6

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 6
        assert buf[:6] == b"abcdef"
        assert rb.n_avail == 0

    def test_read_less_than_available(self):
        """Test reading fewer bytes than available."""
        rb = RingBuffer(10)
        assert rb.write(b"hello world"[:10]) == 10  # Fill buffer

        buf = bytearray(3)
        n = rb.readinto(buf)
        assert n == 3
        assert buf == b"hel"
        assert rb.n_avail == 7

        n = rb.readinto(buf)
        assert n == 3
        assert buf == b"lo "
        assert rb.n_avail == 4

    def test_read_more_than_available(self):
        """Test reading when buffer has fewer bytes than requested."""
        rb = RingBuffer(10)
        assert rb.write(b"hi") == 2

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 2
        assert buf[:2] == b"hi"
        assert rb.n_avail == 0

    def test_empty_write(self):
        """Test writing empty bytes."""
        rb = RingBuffer(10)
        assert rb.write(b"") == 0
        assert rb.n_avail == 0

    def test_read_from_empty_buffer(self):
        """Test reading from empty buffer."""
        rb = RingBuffer(10)
        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 0
        assert rb.n_avail == 0


class TestRingBufferWraparound:
    """Test wraparound behavior."""

    def test_write_wraparound(self):
        """Test writing that wraps around the end of the buffer."""
        rb = RingBuffer(10)

        # Write and read to advance positions
        assert rb.write(b"12345678") == 8
        buf = bytearray(8)
        rb.readinto(buf)

        # Now write_pos is at 8, writing 5 bytes should wrap
        assert rb.write(b"abcde") == 5
        assert rb.n_avail == 5

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 5
        assert buf[:5] == b"abcde"

    def test_read_wraparound(self):
        """Test reading that wraps around the end of the buffer."""
        rb = RingBuffer(10)

        # Position pointers near the end
        assert rb.write(b"12345678") == 8
        buf = bytearray(6)
        rb.readinto(buf)  # read_pos now at 6

        # Write wrapping data
        assert rb.write(b"abcdefgh") == 8  # write_pos wraps around
        assert rb.n_avail == 10

        # Read wrapping data
        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 10
        assert buf[:10] == b"78abcdefgh"

    def test_full_cycle_wraparound(self):
        """Test multiple full cycles of wrap around."""
        rb = RingBuffer(5)

        for _ in range(3):
            assert rb.write(b"abc") == 3
            buf = bytearray(5)
            n = rb.readinto(buf)
            assert n == 3
            assert buf[:3] == b"abc"


class TestRingBufferOverflow:
    """Test buffer overflow behavior."""

    def test_overflow_discards_old_data(self):
        """Test that overflow discards oldest data."""
        rb = RingBuffer(5)

        assert rb.write(b"12345") == 5  # Fill buffer
        assert rb.n_avail == 5

        assert rb.write(b"abc") == 3  # Overflow by 3
        assert rb.n_avail == 5  # Still at capacity

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 5
        # First byte should be 0x00 (marker), then last 4 bytes of new data
        assert buf[0] == 0x00
        assert buf[1:5] == b"5abc"

    def test_overflow_marker_placement(self):
        """Test that 0x00 marker is placed at the oldest surviving byte."""
        rb = RingBuffer(8)

        assert rb.write(b"ABCDEFGH") == 8  # Fill buffer
        assert rb.write(b"XYZ") == 3  # Overflow by 3, discards ABC

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 8
        # 0x00 marker replaces 'D' (oldest surviving byte)
        assert buf[0] == 0x00
        assert buf[1:8] == b"EFGHXYZ"  # Remaining old + new

    def test_large_overflow(self):
        """Test overflow larger than buffer size."""
        rb = RingBuffer(5)

        assert rb.write(b"12345") == 5  # Fill buffer
        assert rb.write(b"abcdefghij") == 10  # Write more than buffer size

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 5
        # Should have 0x00 marker and last 4 bytes of the write
        assert buf[0] == 0x00
        assert buf[1:5] == b"ghij"

    def test_exact_overflow(self):
        """Test overflow that exactly fills the buffer."""
        rb = RingBuffer(5)

        assert rb.write(b"123") == 3
        assert rb.write(b"4567") == 4  # Overflow by 2, discards "12"

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 5
        # First byte is 0x00 marker (replaces "3"), then "4567"
        assert buf[0] == 0x00
        assert buf[1:5] == b"4567"

    def test_no_overflow_when_space_available(self):
        """Test that no overflow occurs when space is available."""
        rb = RingBuffer(10)

        assert rb.write(b"hello") == 5
        buf = bytearray(3)
        rb.readinto(buf)  # Read 3, leaving 2

        assert rb.write(b"world") == 5  # Total: 2 + 5 = 7, no overflow
        assert rb.n_avail == 7

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 7
        assert buf[:7] == b"loworld"
        # No 0x00 marker since no overflow occurred
        assert 0x00 not in buf[:7]


class TestRingBufferNoDrop:
    """Test drop=False writes"""

    def test_start(self):
        """Test that drop=False stops in the buffer"""
        rb = RingBuffer(5)
        assert rb.write(b"123", drop=False) == 3
        assert rb.write(b"456", drop=False) == 2
        assert rb.write(b"789", drop=False) == 0

        buf = bytearray(6)
        assert rb.readinto(buf) == 5
        assert buf[:5] == b"12345"

    def test_mid(self):
        """Test that drop=False works correctly when wrapping"""
        rb = RingBuffer(4)
        assert rb.write(b"123", drop=False) == 3

        buf = bytearray(1)
        assert rb.readinto(buf) == 1
        assert buf == b"1"
        assert rb.readinto(buf) == 1
        assert buf == b"2"

        assert rb.write(b"456", drop=False) == 3
        assert rb.write(b"789", drop=False) == 0

        buf = bytearray(6)
        assert rb.readinto(buf) == 4
        assert buf[:4] == b"3456"


class TestRingBufferEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_byte_buffer(self):
        """Test buffer with size 1."""
        rb = RingBuffer(1)

        assert rb.write(b"a") == 1
        assert rb.n_avail == 1

        buf = bytearray(1)
        n = rb.readinto(buf)
        assert n == 1
        assert buf == b"a"

    def test_single_byte_overflow(self):
        """Test overflow in single byte buffer."""
        rb = RingBuffer(1)

        assert rb.write(b"a") == 1
        assert rb.write(b"b") == 1  # Overflow

        buf = bytearray(1)
        n = rb.readinto(buf)
        assert n == 1
        assert buf[0] == 0x00  # Marker

    def test_alternating_write_read(self):
        """Test alternating small writes and reads."""
        rb = RingBuffer(10)

        for i in range(10):
            assert rb.write(bytes([ord("a") + i])) == 1
            assert rb.n_avail == 1

            buf = bytearray(1)
            n = rb.readinto(buf)
            assert n == 1
            assert buf[0] == ord("a") + i

    def test_fill_empty_cycle(self):
        """Test repeatedly filling and emptying the buffer."""
        rb = RingBuffer(8)

        for _ in range(5):
            assert rb.write(b"12345678") == 8
            assert rb.n_avail == 8

            buf = bytearray(8)
            n = rb.readinto(buf)
            assert n == 8
            assert buf == b"12345678"
            assert rb.n_avail == 0

    def test_partial_read_then_overflow(self):
        """Test overflow after partial read."""
        rb = RingBuffer(5)

        assert rb.write(b"ABCDE") == 5  # Fill
        buf = bytearray(2)
        rb.readinto(buf)  # Read 2, leaving ABC at positions 2,3,4
        assert buf == b"AB"
        assert rb.n_avail == 3

        assert rb.write(b"XYZ12") == 5  # Write 5 more (total would be 8, overflow by 3)
        assert rb.n_avail == 5

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 5
        # Expect: marker + "EXY" + "Z12" but need to verify exact behavior
        assert buf[0] == 0x00

    def test_write_exact_buffer_size(self):
        """Test writing exactly buffer size at once."""
        rb = RingBuffer(10)

        assert rb.write(b"0123456789") == 10
        assert rb.n_avail == 10

        buf = bytearray(10)
        n = rb.readinto(buf)
        assert n == 10
        assert buf == b"0123456789"

    def test_multiple_small_writes_then_large_read(self):
        """Test accumulating data with small writes, then reading all."""
        rb = RingBuffer(20)

        assert rb.write(b"ab") == 2
        assert rb.write(b"cd") == 2
        assert rb.write(b"ef") == 2
        assert rb.write(b"gh") == 2
        assert rb.n_avail == 8

        buf = bytearray(20)
        n = rb.readinto(buf)
        assert n == 8
        assert buf[:8] == b"abcdefgh"

    def test_zero_byte_operations(self):
        """Test that zero-byte reads work correctly."""
        rb = RingBuffer(10)
        assert rb.write(b"test") == 4

        buf = bytearray(0)
        n = rb.readinto(buf)
        assert n == 0
        assert rb.n_avail == 4  # Data still there


class TestRingBufferInvariants:
    """Test that buffer maintains invariants."""

    def test_avail_never_exceeds_buffer_size(self):
        """Test that n_avail never reports more than buffer size."""
        rb = RingBuffer(10)

        for size in [5, 10, 15, 20]:
            assert rb.write(b"X" * size) == size
            assert rb.n_avail <= 10

    def test_read_never_returns_more_than_requested(self):
        """Test that readinto never returns more than buffer size."""
        rb = RingBuffer(10)
        assert rb.write(b"0123456789") == 10

        for req_size in [1, 5, 10]:
            assert rb.write(b"0123456789") == 10
            buf = bytearray(req_size)
            n = rb.readinto(buf)
            assert n <= req_size
            rb.readinto(bytearray(20))  # Clear for next iteration

    def test_consistent_state_after_operations(self):
        """Test buffer state remains consistent."""
        rb = RingBuffer(10)

        assert rb.write(b"hello") == 5
        count1 = rb.n_avail

        buf = bytearray(3)
        n = rb.readinto(buf)
        count2 = rb.n_avail

        assert count2 == count1 - n
