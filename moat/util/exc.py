"""
Exception handling helpers
"""

from __future__ import annotations
from anyio import get_cancelled_exc_class

__all__ = ["exc_iter", "ungroup", "ExpectedError", "ExpKeyError",
           ]


class ExpectedError(Exception):
    """
    An error that shouldn't elicit a traceback
    """
    def __init__(self, exc):
        self.exc = exc

class ExpKeyError(KeyError,ExpectedError):
    "unreported key error"
    pass

def exc_iter(exc):
    """
    iterate over all non-exceptiongroup parts of an exception(group)
    """
    if isinstance(exc, BaseExceptionGroup):
        for e in exc.exceptions:
            yield from exc_iter(e)
    else:
        yield exc


class ungroup:
    """
    A sync+async context manager that unwraps single-element
    exception groups.
    """

    def __call__(self):
        "Singleton. Returns itself."
        return self

    def one(self, e):
        "convert the exceptiongroup @e to a single exception"
        if not isinstance(e, BaseExceptionGroup):
            return e

        Cancel = get_cancelled_exc_class()
        c,e = e.split(Cancel)
        if not e:
            e = c

        while isinstance(e, BaseExceptionGroup):
            if len(e.exceptions) != 1:
                break
            e = e.exceptions[0]
        return e

    def __enter__(self):
        return self

    async def __aenter__(self):
        return self

    def __exit__(self, c, e, t):
        if e is None:
            return
        e = self.one(e)
        raise e from None

    async def __aexit__(self, c, e, t):
        return self.__exit__(c, e, t)


ungroup = ungroup()
