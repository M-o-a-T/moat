"""
``moat dev heat migrate``: the one-shot migration from the legacy
controller (HEAT.md §4.1). The work is done in `moat.dev.heat.system.migrate`.
"""

from __future__ import annotations

import anyio
from pathlib import Path as FSPath

import asyncclick as click

from moat.util import yload
from moat.lib.path import Path  # used with isinstance
from moat.util.time import time

from typing import Any

__all__ = ["cli"]


@click.command(short_help="Migrate the legacy controller's config and state to MoaT-Link.")
@click.option(
    "-c",
    "--config",
    "cfg_file",
    type=click.Path(exists=True, dir_okay=False, path_type=FSPath),
    help="The production YAML file of the legacy controller.",
)
@click.option(
    "-s",
    "--state",
    "state_file",
    type=click.Path(exists=True, dir_okay=False, path_type=FSPath),
    help="Read the legacy state from this file (default: where the config says).",
)
@click.option("--no-state", is_flag=True, help="Don't migrate the state.")
@click.option("--commit", is_flag=True, help="Write the items (default: dry run).")
@click.option("-v", "--verbose", is_flag=True, help="Also print the dropped keys.")
@click.pass_obj
async def cli(
    obj: Any,
    cfg_file: FSPath | None,
    state_file: FSPath | None,
    no_state: bool,
    commit: bool,
    verbose: bool,
) -> None:
    """
    Map the legacy configuration (built-in defaults plus the ``-c`` file)
    and state to the units' ``cfg.app.heat.*`` and ``app.heat.*.state``
    items. Without ``--commit``, print what would change and the items.
    """
    from moat.link.client import Link  # noqa: PLC0415

    from .system.migrate import (  # noqa: PLC0415
        Migration,
        dropped,
        legacy_config,
        map_config,
        map_state,
        migrate,
    )

    cfg = legacy_config(None if cfg_file is None else await anyio.Path(cfg_file).read_text())
    if verbose:
        for k, why in dropped(cfg):
            print(f"# dropped {k}: {why}")

    async with Link(obj.cfg.link) as link:
        state = None
        if not no_state:
            if state_file is not None:
                state = yload(await anyio.Path(state_file).read_text(), attr=True)
            elif isinstance(cfg.state, Path):
                try:
                    state = await link.d_get(cfg.state)
                except KeyError:
                    state = None
            else:
                state = yload(await anyio.Path(cfg.state).read_text(), attr=True)

        mig = Migration(map_config(cfg), map_state(state, time()))
        diff = await migrate(link, mig, commit=commit)
    for line in diff:
        print(line)
    if not commit:
        print(mig.dump())
        print("# dry run; use --commit to write" if diff else "# nothing to do")
