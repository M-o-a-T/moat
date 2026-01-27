"""
Test the callback framework
"""

from __future__ import annotations

try:
    from tests.moat_micro.cffi.test import ItestWrapper
except ImportError:
    # local import
    from test import ItestWrapper


class Fn:
    """Helper class for callback testing."""

    def __init__(self, param: int):
        self.param = param

    def cb(self, param):
        """Callback that multiplies self.param by the given param."""
        return self.param * param


def test_itest():
    """Test the CFFI callback framework."""
    with ItestWrapper(Fn(2).cb, 5) as test:
        assert test.call(3) == 90


if __name__ == "__main__":
    with ItestWrapper(Fn(2).cb, 5) as test:
        print(test.call(3))
