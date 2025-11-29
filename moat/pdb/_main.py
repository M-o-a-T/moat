"Rudimentary debugging."

from __future__ import annotations

import asyncclick as click

from moat.util.main import main_


@main_.command(short_help="Import the debugger")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
async def cli(args):  # pylint: disable=unused-argument  # safe
    """
    This command imports PDB and continues to process arguments.
    """
    breakpoint()  # noqa:T100
    if not args:
        return
    return await main_.main(args)
