"""
Exception handling helpers
"""

from __future__ import annotations

from contextlib import contextmanager

__all__ = ["exc_iter", "ungroup"]


def exc_iter(exc):
    """
    iterate over all non-exceptiongroup parts of an exception(group)
    """
    if isinstance(exc, BaseExceptionGroup):
        for e in exc.exceptions:
            yield from exc_iter(e)
    else:
        yield exc


@contextmanager
def ungroup():
    """
    Unwraps single-member exception groups for easier handling in
    high-level error reporting.
    """
    try:
        yield None
    except BaseException as e:
        while isinstance(e, BaseExceptionGroup):
            if len(e.exceptions) == 1:
                e = e.exceptions[0]
        raise e from None
