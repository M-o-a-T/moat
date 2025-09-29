# noqa:D104 pylint:disable=missing-module-docstring

# We need to ensure that the test interpreter exists
from __future__ import annotations

from pathlib import Path
from subprocess import run


def make_upy(force: bool = False):  # noqa: D103
    p = Path("ext/micropython/ports/unix")
    upy = p / "build-standard/micropython"
    if not force and upy.exists():
        return
    if upy.exists():
        run(["make", "clean"], cwd=p, check=True)
    run(["make", "STRIP=", "DEBUG=1"], cwd=p, check=True)


make_upy()
