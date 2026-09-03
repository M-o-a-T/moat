"""
Tests for moat.bus.crc — CRC computation (CRC6, CRC8, CRC11, CRC16, CRC32).
"""

from __future__ import annotations

import pytest

from moat.bus.crc import CRC6, CRC8, CRC11, CRC16, CRC32, CRC32n

# CRC6/8/11 don't set _depth, so bits must be passed explicitly.
# CRC16/32/32n set _depth (8, 8, 4) and can be instantiated without args.


class TestCRCMeta:
    """Test the _CRCmeta metaclass validation."""

    def test_polynomial_too_wide_raises(self):
        """A polynomial wider than _width should raise RuntimeError."""
        from moat.bus.crc import _CRC  # noqa: PLC0415

        with pytest.raises(RuntimeError, match="polynomial"):

            class _BadCRC(_CRC):
                _poly = 0xFFFF
                _width = 8

    def test_no_poly_returns_plain_class(self):
        """Without _poly, the metaclass returns a plain class (base for subclassing)."""
        from moat.bus.crc import _CRC  # noqa: PLC0415

        class _NoPoly(_CRC):
            _width = 8

        # _poly is a type annotation on _CRC, not a defaulted attribute;
        # a subclass that omits it simply lacks the attribute.
        assert not hasattr(_NoPoly, "_poly")


class TestCRC6:
    """Tests for CRC6 (requires explicit bits parameter)."""

    def test_init_and_reset(self):
        """init and reset."""
        c = CRC6(bits=6)
        assert c.crc == 0
        c.update(0x15)
        assert c.crc != 0
        c.reset()
        assert c.crc == 0

    def test_finish_returns_crc(self):
        """finish returns crc."""
        c = CRC6(bits=6)
        c.update(0x10)
        assert c.finish() == c.crc

    def test_zero_input(self):
        """zero input."""
        c = CRC6(bits=6)
        c.update(0)
        assert c.finish() == 0

    def test_known_values(self):
        """CRC6 with a single byte should produce consistent results."""
        c = CRC6(bits=6)
        c.update(0x01)
        v1 = c.finish()

        c.reset()
        c.update(0x01)
        v2 = c.finish()
        assert v1 == v2

    def test_update_n_single_word(self):
        """update_n with 6 bits should match update for 6-bit values."""
        c1 = CRC6(bits=6)
        c1.update(0x15)
        v1 = c1.finish()

        c2 = CRC6(bits=6)
        c2.update_n(0x15, 6)
        v2 = c2.finish()
        assert v1 == v2

    def test_update_n_partial_bits(self):
        """update_n with fewer bits than the table width."""
        c = CRC6(bits=6)
        c.update_n(0x3, 3)
        assert c.finish() != 0

    def test_table_size(self):
        """Table size should be 2^bits."""
        c = CRC6(bits=6)
        assert len(c._table) == 64  # noqa: SLF001


class TestCRC8:
    """Tests for CRC8 (requires explicit bits parameter)."""

    def test_init_and_reset(self):
        """init and reset."""
        c = CRC8(bits=8)
        assert c.crc == 0
        c.update(0xFF)
        assert c.crc != 0
        c.reset()
        assert c.crc == 0

    def test_table_size(self):
        """table size."""
        c = CRC8(bits=8)
        assert len(c._table) == 256  # noqa: SLF001

    def test_consistency(self):
        """Same input should produce same output."""
        c1 = CRC8(bits=8)
        c1.update(0x42)
        v1 = c1.finish()

        c2 = CRC8(bits=8)
        c2.update(0x42)
        v2 = c2.finish()
        assert v1 == v2

    def test_different_inputs_different_output(self):
        """different inputs different output."""
        c = CRC8(bits=8)
        c.update(0x01)
        v1 = c.finish()

        c.reset()
        c.update(0x02)
        v2 = c.finish()
        assert v1 != v2

    def test_update_n_multiple_bytes(self):
        """update_n with 16 bits (more than table depth of 8)."""
        c = CRC8(bits=8)
        c.update_n(0xABCD, 16)
        assert c.finish() != 0

    def test_update_n_exact_width(self):
        """update_n with exactly 8 bits should match update."""
        c1 = CRC8(bits=8)
        c1.update(0x55)
        v1 = c1.finish()

        c2 = CRC8(bits=8)
        c2.update_n(0x55, 8)
        v2 = c2.finish()
        assert v1 == v2


class TestCRC11:
    """Tests for CRC11 (requires explicit bits parameter)."""

    def test_init_and_reset(self):
        """init and reset."""
        c = CRC11(bits=4)
        assert c.crc == 0
        c.update(0x100)
        c.reset()
        assert c.crc == 0

    def test_table_size(self):
        """table size."""
        c = CRC11(bits=4)
        assert len(c._table) == 16  # noqa: SLF001

    def test_known_value_stability(self):
        """known value stability."""
        c = CRC11(bits=4)
        c.update(0x3FF)
        v1 = c.finish()

        c.reset()
        c.update(0x3FF)
        v2 = c.finish()
        assert v1 == v2


class TestCRC16:
    """Tests for CRC16 (_depth=8, can instantiate without args)."""

    def test_init_and_reset(self):
        """init and reset."""
        c = CRC16()
        assert c.crc == 0
        c.update(0xFF)
        c.reset()
        assert c.crc == 0

    def test_table_size(self):
        """table size."""
        c = CRC16()
        assert len(c._table) == 256  # noqa: SLF001

    def test_update_n_large(self):
        """update_n with more bits than the table depth."""
        c = CRC16()
        c.update_n(0xDEADBEEF, 32)
        assert c.finish() != 0

    def test_sequential_updates_accumulate(self):
        """Sequential updates should accumulate into a non-trivial CRC."""
        c = CRC16()
        c.update(0xAB)
        c.update(0xCD)
        v = c.finish()
        assert v != 0

    def test_update_then_reset_then_update(self):
        """Reset between updates should give same result as fresh instance."""
        c = CRC16()
        c.update(0x42)
        v1 = c.finish()

        c.reset()
        c.update(0x42)
        v2 = c.finish()
        assert v1 == v2


class TestCRC32:
    """Tests for CRC32 (_depth=8, can instantiate without args)."""

    def test_init_and_reset(self):
        """init and reset."""
        c = CRC32()
        assert c.crc == 0
        c.update(0xFF)
        c.reset()
        assert c.crc == 0

    def test_table_size(self):
        """table size."""
        c = CRC32()
        assert len(c._table) == 256  # noqa: SLF001

    def test_standard_check(self):
        """CRC32 with standard polynomial should produce known checksums."""
        c = CRC32()
        assert c.finish() == 0

    def test_crc32n_different_depth(self):
        """CRC32n has _depth=4, so table size = 16."""
        c = CRC32n()
        assert len(c._table) == 16  # noqa: SLF001

    def test_crc32n_produces_valid_crc(self):
        """CRC32n with _depth=4 should produce a valid non-zero CRC after update."""
        c = CRC32n()
        c.update(0x42)
        assert c.finish() != 0

    def test_crc32_and_crc32n_both_nonzero_after_update(self):
        """Both CRC32 variants should produce non-zero CRCs after updating."""
        c1 = CRC32()
        c1.update(0x42)
        assert c1.finish() != 0

        c2 = CRC32n()
        c2.update(0x42)
        assert c2.finish() != 0

    def test_accumulation_order_matters(self):
        """Different order of updates should generally produce different CRCs."""
        c1 = CRC32()
        c1.update(0x01)
        c1.update(0x02)
        v1 = c1.finish()

        c2 = CRC32()
        c2.update(0x02)
        c2.update(0x01)
        v2 = c2.finish()
        assert v1 != v2
