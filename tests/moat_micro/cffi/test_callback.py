"""
Test the callback framework
"""

from __future__ import annotations

try:
    from tests.moat_micro.cffi.test import Test
except ImportError:
    # local import
    from test import Test


class Fn:
    """Helper class for callback testing."""

    def __init__(self, param: int):
        self.param = param

    def cb(self, param):
        """Callback that multiplies self.param by the given param."""
        return self.param * param


def test_itest():
    """Test the CFFI callback framework."""
    with Test(Fn(2).cb, 5) as test:
        assert test.call(3) == 90


if __name__ == "__main__":
    with Test(Fn(2).cb, 5) as test:
        print(test.call(3))
