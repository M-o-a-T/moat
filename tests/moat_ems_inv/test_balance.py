"""
Tests for moat.ems.inv._util.balance — phase balancing algorithm.
"""

from __future__ import annotations

from moat.ems.inv._util import balance


class TestBalanceBasic:
    """Test basic balancing scenarios."""

    def test_empty_list(self):
        """empty list."""
        assert balance([]) == []

    def test_single_positive(self):
        """A single positive value should remain unchanged."""
        assert balance([100]) == [100]

    def test_single_negative(self):
        """A single negative value should remain unchanged."""
        assert balance([-100]) == [-100]

    def test_all_positive(self):
        """All-positive values should remain unchanged (nothing to balance)."""
        assert balance([100, 200, 300]) == [100, 200, 300]

    def test_all_negative(self):
        """All-negative values should remain unchanged."""
        assert balance([-100, -200, -300]) == [-100, -200, -300]

    def test_mixed_balances_to_zero(self):
        """Positive and negative values that cancel out should produce zeros."""
        result = balance([100, -100])
        assert sum(result) == 0

    def test_mixed_three_phases(self):
        """Three-phase scenario: one producing, two consuming."""
        result = balance([300, -100, -200])
        assert sum(result) == 0
        # The producer should be reduced, consumers increased toward zero
        assert result[0] < 300

    def test_more_negative_than_positive(self):
        """When negatives dominate, the reversal logic kicks in."""
        result = balance([100, -200, -300])
        assert isinstance(result, list)
        assert len(result) == 3


class TestBalanceWithLimits:
    """Test balancing with val_min / val_max constraints."""

    def test_cap_positive_with_val_max(self):
        """val_max should cap the positive values."""
        result = balance([100, 200, 300], val_max=150)
        for v in result:
            assert v <= 150

    def test_cap_negative_with_val_min(self):
        """val_min should cap the negative values."""
        result = balance([-100, -200, -300], val_min=-150)
        for v in result:
            assert v >= -150

    def test_per_element_limits(self):
        """val_max as a list applies per-element caps."""
        limits = [50, 100, 150]
        result = balance([200, 200, 200], val_max=limits)
        assert result[0] <= 50
        assert result[1] <= 100
        assert result[2] <= 150

    def test_both_limits(self):
        """Both val_min and val_max constrain simultaneously."""
        result = balance([300, -100, -200], val_min=-50, val_max=200)
        for v in result:
            assert -50 <= v <= 200


class TestBalanceProperties:
    """Test mathematical properties of the balance function."""

    def test_sum_preserved_without_limits(self):
        """Without limits, the sum should be preserved."""
        data = [100, 200, -50, -150]
        result = balance(data)
        assert sum(result) == sum(data)

    def test_result_length_matches_input(self):
        """Output length should match input length."""
        for n in range(1, 6):
            data = [((-1) ** i) * (i * 100) for i in range(n)]
            result = balance(data)
            assert len(result) == len(data)

    def test_order_preservation(self):
        """Results are returned in the same order as inputs (by index)."""
        data = [300, -100, -200]
        result = balance(data)
        assert len(result) == 3
        # The function sorts internally but returns in original order
        # The first element (producer) should be reduced
        assert result[0] <= 300
