"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

import sys
from functools import partial
from types import CodeType, ModuleType

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ["Module", "make_module", "make_proc"]


def _call_proc(code: CodeType, variables: Sequence[str], *a: Any, **kw: Any) -> Any:
    v = variables[len(a) :]
    if v:
        a_list = list(a)
        for k in v:
            a_list.append(kw.pop(k, None))
        a = tuple(a_list)
    eval(code, kw)
    code_fn = kw["_proc"]
    return code_fn(*a)


def make_proc(
    code: str, variables: Sequence[str], path: Any, *, use_async: bool = False
) -> Callable[..., Any]:
    """Compile this code block to a procedure.

    Args:
        code: the code block to execute. Text, will be indented.
        variables: variable names to pass into the code
        path: the location where the code is stored
        use_async: False if sync code, True if async, None if in thread
    Returns:
        the procedure to call. All keyval arguments will be in the local
        dict.
    """
    hdr = f"""\
def _proc({",".join(variables)}):
    """

    if use_async:
        hdr = "async " + hdr
    code_str = hdr + code.replace("\n", "\n    ")
    code_obj = compile(code_str, str(path), "exec")

    return partial(_call_proc, code_obj, variables)


class Module(ModuleType):
    """A dynamically-loaded module.

    TODO.
    """

    def __repr__(self) -> str:
        return f"<Module {self.__class__.__name__}%s>"


def make_module(code: str, path: Sequence[Any]) -> ModuleType:
    """Compile this code block to something module-ish.

    Args:
        code: the code block to execute
        path: the location where the code is / shall be stored
    Returns:
        the procedure to call. All keyval arguments will be in the local
        dict.
    """
    name = ".".join(str(x) for x in path)
    code_obj = compile(code, name, "exec")
    m = sys.modules.get(name, None)
    if m is None:
        m = ModuleType(name)
    eval(code_obj, m.__dict__)
    sys.modules[name] = m
    return m
