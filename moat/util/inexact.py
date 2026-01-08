"""
Floats that compare with a delta.
"""

from __future__ import annotations

from math import isclose

__all__ = ["InexactFloat"]


class InexactFloat(float):
    """This is a wrapper for `float`that supports inexact comparison and
    output of float numbers.

    Comparison is mediated by :py:func:`math.isclose`.

    If both sides are an :py:class:`InexactFloat`, numbers are considered
    equal if either is within the tolerances of the other.

    The number of significant digits does not affect the comparison.

    This class only affects comparison, but not any other mathematical
    operation.

    .. note::
        Inexact equality is not transitive: a=b and b=c is not sufficient
        for a=c.
    """

    __slots__ = ("abs", "digits", "rel")

    def __new__(cls, val, rel=1e-06, abs=1e-12, digits=3):  # noqa: A002
        """
        Args:
            val: the exact value.
            rel: Acceptable relative error.
            abs: Acceptable absolute error.
            digits: Number of significant digits.

        """
        res = super().__new__(cls, val)
        res._rel = rel
        res._abs = abs
        res._digits = digits
        return res

    def __hash__(self):
        raise TypeError(f"unhashable type: {type(self)}")

    def __eq__(self, b):
        """Check if the two floats are mostly-equal."""
        if isclose(self, b, rel_tol=self._rel, abs_tol=self._abs):
            return True
        if not isinstance(b, InexactFloat):
            return False
        return isclose(b, self, rel_tol=b._rel, abs_tol=b._abs)

    def __ne__(self, b):
        return not self.__eq__(b)

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
        return f"{round(self, self._digits):.{self._digits}f}"
