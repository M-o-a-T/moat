"""
Tests for moat.bus.util — minifloat conversion (mini2byte / byte2mini).
"""

from __future__ import annotations

import pytest

from moat.bus.util import MINI_F, byte2mini, mini2byte


class TestMini2Byte:
    """Test the mini2byte function (float → minifloat byte)."""

    def test_zero(self):
        """zero."""
        assert mini2byte(0) == 0

    def test_small_values(self):
        """Values 0..8 in steps of 0.25 map directly (denormalized)."""
        assert mini2byte(0.25) == 1
        assert mini2byte(0.5) == 2
        assert mini2byte(1.0) == 4
        assert mini2byte(2.0) == 8
        assert mini2byte(4.0) == 16
        assert mini2byte(8.0) == 32

    def test_negative_raises(self):
        """negative raises."""
        with pytest.raises(ValueError, match="negative"):
            mini2byte(-1.0)

    def test_clipping_large_values(self):
        """Very large values should clip to 0xFF."""
        assert mini2byte(1e18) == 0xFF
        assert mini2byte(1e6) == 0xFF

    def test_boundary_0x20(self):
        """The value 0x20 (32 = 8.0) is the upper bound of denormalized range."""
        assert mini2byte(8.0) == 32

    def test_normalized_values(self):
        """Values above 8.0 use the exponent/mantissa encoding."""
        # At 8.0, we're at the boundary; 9.0 should be in normalized territory
        v = mini2byte(9.0)
        assert v > 32  # enters normalized range
        # Round-trip should be approximately correct
        assert abs(byte2mini(v) - 9.0) < 1.0

    def test_progressive_values(self):
        """Progressively larger values should produce progressively larger bytes."""
        vals = [0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0]
        bytes_out = [mini2byte(v) for v in vals]
        for i in range(1, len(bytes_out)):
            assert bytes_out[i] >= bytes_out[i - 1]


class TestByte2Mini:
    """Test the byte2mini function (minifloat byte → float)."""

    def test_zero(self):
        """zero."""
        assert byte2mini(0) == 0.0

    def test_denormalized_range(self):
        """Bytes 0..32 map to 0..8.0 in steps of 0.25."""
        assert byte2mini(0) == 0.0
        assert byte2mini(1) == 0.25
        assert byte2mini(2) == 0.5
        assert byte2mini(4) == 1.0
        assert byte2mini(8) == 2.0
        assert byte2mini(16) == 4.0
        assert byte2mini(32) == 8.0

    def test_normalized_range(self):
        """Bytes above 32 use exponent + mantissa encoding."""
        # byte 33: exp=(33>>4)-1=1, mantissa=33&0xF=1, so (2)*(0x10+1)*0.25 = 2*17*0.25 = 8.5
        assert byte2mini(33) == 8.5

    def test_high_byte(self):
        """Byte 0xFF is the maximum representable value."""
        v = byte2mini(0xFF)
        assert v > 0
        assert v > 100000  # should be very large


class TestRoundTrip:
    """Test round-trip conversion: mini2byte(byte2mini(x)) ≈ x."""

    @pytest.mark.parametrize("byte_val", range(256))
    def test_round_trip_all_bytes(self, byte_val):
        """For every byte value, byte2mini then mini2byte should give back the same byte."""
        f = byte2mini(byte_val)
        b = mini2byte(f)
        assert b == byte_val, f"byte {byte_val}: byte2mini={f}, mini2byte={b}"

    def test_mini_f_constant(self):
        """MINI_F should be 0.25."""
        assert MINI_F == 0.25
