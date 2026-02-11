"""
Exception handling helpers

This code is *duplicated* in moat.micro:_embed/lib/moat/util/exc.py
"""

from __future__ import annotations

import os
from anyio import get_cancelled_exc_class

from moat.lib.micro import log

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from typing import Self

__all__ = [
    "ExpAttrError",
    "ExpKeyError",
    "ExpectedError",
    "exc_iter",
    "run_no_exc",
    "ungroup",
]


class ExpectedError(Exception):
    """
    An error that shouldn't elicit a traceback
    """

    def __init__(self, exc: BaseException) -> None:
        self.exc: BaseException = exc


class ExpKeyError(KeyError, ExpectedError):
    "unreported key error"

    pass


class ExpAttrError(AttributeError, ExpectedError):
    "unreported key error"

    pass


def exc_iter(exc: BaseException) -> Iterator[BaseException]:
    """
    iterate over all non-exceptiongroup parts of an exception(group)
    """
    if isinstance(exc, BaseExceptionGroup):
        for e in exc.exceptions:
            yield from exc_iter(e)
    else:
        yield exc


class _Ungroup:
    """
    A sync+async context manager that unwraps single-element
    exception groups.
    """

    def __call__(self) -> Self:
        "Singleton. Returns itself."
        return self

    @staticmethod
    def one(e: BaseException) -> BaseException:
        "convert the exceptiongroup @e to a single exception"
        if not isinstance(e, BaseExceptionGroup):
            return e

        try:
            Cancel = get_cancelled_exc_class()
        except Exception:  # noqa:S110  # no need to be more selective
            pass
        else:
            c, e_split = e.split(Cancel)
            if e_split is not None:
                e = e_split
            elif c is not None:
                e = c

        while isinstance(e, BaseExceptionGroup):
            if len(e.exceptions) != 1:
                break
            e = e.exceptions[0]
        return e

    def __enter__(self) -> Self:
        return self

    async def __aenter__(self) -> Self:
        return self

    def __exit__(
        self,
        c: type[BaseException] | None,
        e: BaseException | None,
        t: object,
    ) -> None:
        if e is None:
            return
        if "MOAT_TB" in os.environ:
            return
        e = self.one(e)
        raise e from None

    async def __aexit__(
        self,
        c: type[BaseException] | None,
        e: BaseException | None,
        t: object,
    ) -> None:
        return self.__exit__(c, e, t)


ungroup: _Ungroup = _Ungroup()


async def run_no_exc(
    p: Callable[..., Any],
    msg: dict[str, Any],
    x_err: tuple[type[Exception], ...] = (),
) -> None:
    """
    Call p(msg) but log exceptions.

    Args:
        p: Callable to execute.
        msg: Keyword arguments to pass to the callable.
        x_err: Exception types to log with reduced detail.
    """
    try:
        r = p(**msg)
        if hasattr(r, "throw"):  # coroutine
            r = await r
    except x_err as err:
        log("Error in %r %r: %r", p, msg, err)
    except Exception as err:
        log("Error in %r %r", p, msg, err=err)
