"""
Callback framework
"""

from __future__ import annotations


class Test:
    def __init__(self, fn):
        self.fn = fn

    def __enter__(self) -> Self:
        "dynamically load itest.so here"
        self.itest = ...
        return self

    def __exit__(self, *exc):
        "unload itest.so"
        del self.itest

    def call(self, param: int) -> int:
        "call itest_call(param) and return its result"
        return ...
