"""
Exception handling helpers

This code is *duplicated* in moat.micro:_embed/lib/moat/util/exc.py
"""

from __future__ import annotations
import os
from anyio import get_cancelled_exc_class
from sniffio import AsyncLibraryNotFoundError

__all__ = [
    "exc_iter",
    "ungroup",
    "ExpectedError",
    "ExpKeyError",
    "ExpAttrError",
]


class ExpectedError(Exception):
    """
    An error that shouldn't elicit a traceback
    """

    def __init__(self, exc):
        self.exc = exc


class ExpKeyError(KeyError, ExpectedError):
    "unreported key error"

    pass


class ExpAttrError(AttributeError, ExpectedError):
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

    @staticmethod
    def one(e):
        "convert the exceptiongroup @e to a single exception"
        if not isinstance(e, BaseExceptionGroup):
            return e

        try:
            Cancel = get_cancelled_exc_class()
        except AsyncLibraryNotFoundError:
            pass
        else:
            c, e = e.split(Cancel)
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
        if "MOAT_TB" in os.environ:
            return
        e = self.one(e)
        raise e from None

    async def __aexit__(self, c, e, t):
        return self.__exit__(c, e, t)


ungroup = ungroup()
