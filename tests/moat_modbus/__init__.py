# pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations

import anyio


def anyio_run(p, *a, **k):
    if "backend" not in k:
        k["backend"] = "trio"
    return anyio.run(p, *a, **k)
