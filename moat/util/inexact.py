"""
Floats that compare with a delta.
"""

from __future__ import annotations

from math import isclose

__all__ = ["InexactFloat"]


class InexactFloat(float):
    """Float wrapper used for inexact comparison of float record elements."""

    __slots__ = ("abs", "rel", "digits")

    def __new__(cls, val, rel=1e-06, abs=1e-12, digits=3):
        res = super().__new__(cls, val)
        res.rel = rel
        res.abs = abs
        res.digits = digits
        return res

    def __hash__(self):
        raise TypeError(f"unhashable type: {type(self)}")

    def __eq__(self, b):
        """Check if the two floats are mostly-equal."""
        return isclose(self, b, rel_tol=self.rel, abs_tol=self.abs)

    def __ne__(self, b):
        return not isclose(self, b, rel_tol=self.rel, abs_tol=self.abs)

    def __lt__(self, other):
        return super().__lt__(other) and self != other

    def __gt__(self, other):
        return super().__gt__(other) and self != other

    def __le__(self, other):
        return super().__le__(other) or self == other

    def __ge__(self, other):
        return super().__ge__(other) or self == other

    # --repr
    def __repr__(self):
        return f"{type(self).__name__}({super().__repr__()})"

    def __str__(self):
        return f"{round(self, self.digits):.{self.digits}f}"
