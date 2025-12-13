# We need to ensure that the test interpreter exists
from __future__ import annotations

import os
from pathlib import Path
from subprocess import run


def make_upy(force: bool = False):  # noqa: D103
    here = Path.cwd().absolute()
    p = here / "build/mpy-unix"
    upy = p / "micropython"
    var = here / "moat/micro/_embed/boards/unix/test"
    mk = here / "ext/micropython/ports/unix"
    if not force and upy.exists():
        return
    if not p.exists:
        if not p.parent.exists():
            p.parent.mkdir()
        p.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(here)
    run(  # noqa:S603
        ["make", "STRIP=", "DEBUG=1", f"VARIANT_DIR={var}", f"BUILD={p}"],
        cwd=mk,
        check=True,
        env=env,
    )


make_upy()
