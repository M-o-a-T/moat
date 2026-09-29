"""
The ``moat dev`` command group loads all its subgroups, so one broken
import breaks every ``moat dev …`` command (moat-i08).
"""

from __future__ import annotations

import importlib
import pytest
from pathlib import Path

import moat.dev

SUBGROUPS = sorted(
    p.parent.name
    for d in moat.dev.__path__
    for p in Path(d).glob("*/_main.py")
    if p.parent.name != "OFF"
)


def test_found():
    "the list isn't empty by accident"
    assert "sew" in SUBGROUPS
    assert "heat" in SUBGROUPS


@pytest.mark.parametrize("name", SUBGROUPS)
def test_import(name: str) -> None:
    "each subgroup's command module imports"
    importlib.import_module(f"moat.dev.{name}._main")


async def test_help(capfd):
    "``moat dev --help`` lists every subgroup"
    from moat.src.test import run  # noqa: PLC0415

    await run("dev", "--help", do_stdout=False)
    out = capfd.readouterr().out
    for name in SUBGROUPS:
        assert f"  {name} " in out, out
