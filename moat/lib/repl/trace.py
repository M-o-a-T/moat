from __future__ import annotations  # noqa: D100

import os
import sys

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import IO

__all__ = ["trace"]

trace_file: IO[str] | None = None
if trace_filename := os.environ.get("PYREPL_TRACE"):
    trace_file = open(trace_filename, "a")  # noqa: SIM115


if sys.platform == "emscripten":
    from posix import _emscripten_log

    def trace(line: str, *k: object, **kw: object) -> None:  # noqa: D103
        if "PYREPL_TRACE" not in os.environ:
            return
        if k or kw:
            line = line.format(*k, **kw)
        _emscripten_log(line)

else:

    def trace(line: str, *k: object, **kw: object) -> None:  # noqa: D103
        if trace_file is None:
            return
        if k or kw:
            line = line.format(*k, **kw)
        trace_file.write(line + "\n")
        trace_file.flush()
