"""
Floats that compare with a delta.
"""

from __future__ import annotations

from math import isclose

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Self

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

    __slots__ = ("_abs", "_digits", "_rel")

    _rel: float
    _abs: float
    _digits: int

    def __new__(
        cls,
        val: float,
        rel: float = 1e-06,
        abs: float = 1e-12,  # noqa: A002
        digits: int = 3,
    ) -> Self:
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

    def __hash__(self) -> int:
        raise TypeError(f"unhashable type: {type(self)}")

    def __eq__(self, b: object) -> bool:
        """Check if the two floats are mostly-equal."""
        if isinstance(b, int | float | InexactFloat) and isclose(
            self, b, rel_tol=self._rel, abs_tol=self._abs
        ):
            return True
        if not isinstance(b, InexactFloat):
            return False
        return isclose(b, self, rel_tol=b._rel, abs_tol=b._abs)

    def __ne__(self, b: object) -> bool:
        return not self.__eq__(b)

    def __lt__(self, other: float | InexactFloat) -> bool:
        return super().__lt__(other) and self != other

    def __gt__(self, other: float | InexactFloat) -> bool:
        return super().__gt__(other) and self != other

    def __le__(self, other: float | InexactFloat) -> bool:
        return super().__le__(other) or self == other

    def __ge__(self, other: float | InexactFloat) -> bool:
        return super().__ge__(other) or self == other

    # --repr
    def __repr__(self) -> str:
        return f"{type(self).__name__}({super().__repr__()})"

    def __str__(self) -> str:
        return f"{round(self, self._digits):.{self._digits}f}"
