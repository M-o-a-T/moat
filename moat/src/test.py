"""
MoaT test support
"""

from __future__ import annotations

import io
import logging
import shlex
import sys
from contextlib import contextmanager

from asyncscope import main_scope, scope
from moat.util import OptCtx, attrdict, wrap_main, CFG  # pylint:disable=no-name-in-module

logger = logging.getLogger(__name__)


async def run(*args, expect_exit=0, do_stdout=True):
    """Call a MoaT command handler"""
    args = ("-c", "/dev/null", *args)

    if do_stdout:
        CFG["_stdout"] = out = io.StringIO()
    logger.debug(" moat %s", " ".join(shlex.quote(str(x)) for x in args))
    try:
        res = None
        async with (
            OptCtx(main_scope(name="run") if scope.get() is None else None),
            scope.using_scope(),
        ):
            res = await wrap_main(
                args=args,
                wrap=True,
                CFG=CFG,
                cfg=False,
                name="moat",
                sub_pre="moat",
                sub_post="_main.cli",
            )
        if res is None:
            res = attrdict()
        return res
    except SystemExit as exc:
        res = exc
        assert exc.code == expect_exit, exc.code
        return exc
    except Exception as exc:
        while isinstance(exc, ExceptionGroup) and len(exc.exceptions) == 1:
            exc = exc.exceptions[0]
        raise
    except BaseException as exc:
        res = exc
        raise
    else:
        assert expect_exit == 0
        return res
    finally:
        if do_stdout:
            if res is not None:
                res.stdout = out.getvalue()
        CFG.pop("_stdout", None)


class DidNotRaise(Exception):
    pass


@contextmanager
def raises(*exc):
    """
    Like pytest.raises, but handles exception groups
    """
    res = attrdict()
    try:
        yield res
    except exc as e:
        res.value = e
    except ExceptionGroup as e:
        while isinstance(e, ExceptionGroup) and len(e.exceptions) == 1:
            e = e.exceptions[0]
        res.value = e
        if isinstance(e, exc):
            return
        raise
    else:
        res.value = None
        raise DidNotRaise(exc)
