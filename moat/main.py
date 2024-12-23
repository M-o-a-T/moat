"""
This module contains the entry point to the MOAT command line interface
"""

import os
import sys
import anyio
import asyncclick as click
from asyncscope import main_scope
from moat.util import attrdict, main_
from moat.util import exc_iter, ungroup


def cmd(backend="trio"):
    """
    The main command entry point, as declared in ``pyproject.toml``.
    """

    # @click.* decorators change the semantics
    # pylint: disable=no-value-for-parameter
    main_.help = """\
This is the main command handler for MoaT, the Master of all Things.
"""

    async def runner():
        async with main_scope() as m_s:
            obj = attrdict(moat=attrdict(main_scope=m_s, sub_pre="moat", sub_post="_main.cli"))
            await main_.main(obj=obj)

    ec = 0
    try:
        with ungroup:
            anyio.run(runner, backend=backend)
    except BaseException as exc:
        for e in exc_iter(exc):
            if isinstance(e, KeyboardInterrupt):
                if "MOAT_TB" in os.environ:
                    raise
                print("\rInterrupted.   ", file=sys.stderr)
                break
            elif isinstance(e, SystemExit):
                ec |= e.code
            else:
                raise
    return ec


@main_.command(short_help="Import the debugger")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
async def pdb(ctx, args):  # pylint: disable=unused-argument  # safe
    """
    This command imports PDB and continues to process arguments.
    """
    breakpoint()  # pylint: disable=forgotten-debug-statement
    if not args:
        return
    return await main_.main(args)
