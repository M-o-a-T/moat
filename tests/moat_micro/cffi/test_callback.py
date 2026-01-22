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
    def __init__(self, param: int):
        self.param = param

    def cb(self, param):
        return self.param * param


def fn(param: int) -> int:
    return


def test_itest():
    with Test(Fn(5).cb) as test:
        assert test.call(3) == 126
