"""
Support refcounted DLLs.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from cffi import FFI

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@dataclass
class DLLref:
    ffi: FFI
    lib: Any
    stack: ExitStack
    count: int = 0


_libs: dict[str, DLLref] = {}
_lock: Lock = Lock()

__all__ = ["DLL"]


# TODO retrieve real const value
# RTLD_GLOBAL=0x100


@contextmanager
def DLL(id: str, cdef: str, *paths: str | Path) -> tuple[FFI, Any]:
    """
    Refcounted CFFI.dlopen() wrapper.

    Re-using an ID might result in returning a cached library set.

    Returns:
        a (FFI,dlopened-library wrapper) tuple.
    """

    stack = ExitStack()
    with _lock, stack:
        ref = None
        try:
            if id in _libs:
                ref = _libs[id]
                ref.count += 1
            else:
                ffi = FFI()
                ffi.cdef(cdef)
                for p in paths:
                    p = Path(p)  # noqa:PLW2901
                    if not p.exists():
                        raise FileNotFoundError(p)
                    lib = ffi.dlopen(str(p))
                    stack.callback(ffi.dlclose, lib)

                ref = DLLref(stack=stack.pop_all(), ffi=ffi, lib=lib)
                _libs[id] = ref
            yield ffi, lib

        finally:
            if ref is None:
                pass
            elif ref.count:
                ref.count -= 1
            else:
                if _libs.pop(id) is not ref:
                    raise RuntimeError("Nesting problem?")
                ref.stack.close()
