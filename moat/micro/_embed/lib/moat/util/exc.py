"""
Exception handling helpers

This code is *duplicated* in `moat.util.exc`.
"""

from __future__ import annotations

__all__ = [
    "ExpAttrError",
    "ExpKeyError",
    "ExpectedError",
    "exc_iter",
    "ungroup",
]


class ExpKeyError(KeyError):
    "unreported key error"

    pass


class ExpAttrError(AttributeError):
    "unreported key error"

    pass


ExpectedError = (ExpKeyError, ExpAttrError)


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
