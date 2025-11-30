"""
This module contains the entry point to the MOAT command line interface
"""

from __future__ import annotations

import anyio
import os
import sys

import asyncclick as click
from asyncscope import main_scope

from moat.util import NotGiven, attrdict, exc_iter, main_, to_attrdict, ungroup
from moat.util.exc import ExpectedError

__all__ = ["cmd", "run"]


def cmd(backend="trio"):
    "The standard MoaT command line handler"
    return _cmd(attrdict(sub_pre="moat", sub_post="_main.cli"), backend=backend)


def run(main, backend="trio", **kw):
    """
    Run external code in the MoaT environment.
    """
    kw.setdefault("sub_pre", NotGiven)
    kw.setdefault("sub_post", "cli")
    kw.setdefault("ext_pre", NotGiven)
    kw.setdefault("ext_post", "_main.cli")
    kw.setdefault("doc", "Document this command! Use a 'doc=…' argument.")

    kw = to_attrdict(kw)
    kw.main_cmd = main
    return _cmd(kw, backend=backend)


def _cmd(mt: attrdict, backend="trio"):
    """
    The main command entry point, as declared in ``pyproject.toml``.
    """

    # @click.* decorators change the semantics
    # pylint: disable=no-value-for-parameter
    main_.help = mt.get(
        "doc",
        """\
This is the main command handler for MoaT, the Master of all Things.
""",
    )

    async def runner():
        async with main_scope() as mt.main_scope:
            obj = attrdict(moat=mt)
            await main_.main(obj=obj)

    ec = 0
    try:
        with ungroup:
            anyio.run(runner, backend=backend)
    except ExpectedError as exc:
        if "MOAT_TB" in os.environ:
            raise
        print(repr(exc), file=sys.stderr)
        ec = 1
    except click.exceptions.ClickException as exc:
        if "MOAT_TB" in os.environ:
            raise
        print(exc, file=sys.stderr)
        ec = 1
    except BaseException as exc:
        for e in exc_iter(exc):
            if isinstance(e, KeyboardInterrupt):
                if "MOAT_TB" in os.environ:
                    raise
                print("\rInterrupted.   ", file=sys.stderr)
                break
            elif isinstance(e, SystemExit):
                ec |= e.code
            elif isinstance(e, click.exceptions.Exit):
                ec |= e.exit_code
            else:
                raise
    return ec
