"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

import sys
from functools import partial
from types import ModuleType

__all__ = ["make_proc", "Module", "make_module"]


def _call_proc(code, variables, *a, **kw):
    v = variables[len(a) :]
    if v:
        a = list(a)
        for k in v:
            a.append(kw.pop(k, None))
    eval(code, kw)  # noqa: S307 pylint: disable=eval-used
    code = kw["_proc"]
    return code(*a)


def make_proc(code, variables, path, *, use_async=False):  # pylint: disable=redefined-builtin
    """Compile this code block to a procedure.

    Args:
        code: the code block to execute. Text, will be indented.
        vars: variable names to pass into the code
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
    code = hdr + code.replace("\n", "\n    ")
    code = compile(code, str(path), "exec")

    return partial(_call_proc, code, variables)


class Module(ModuleType):
    """A dynamically-loaded module.

    TODO.
    """

    def __repr__(self):
        return f"<Module {self.__class__.__name__}%s>"


def make_module(code, path):
    """Compile this code block to something module-ish.

    Args:
        code: the code block to execute
        path: the location where the code is / shall be stored
    Returns:
        the procedure to call. All keyval arguments will be in the local
        dict.
    """
    name = ".".join(str(x) for x in path)
    code = compile(code, name, "exec")
    m = sys.modules.get(name, None)
    if m is None:
        m = ModuleType(name)
    eval(code, m.__dict__)  # noqa: S307 pylint: disable=eval-used
    sys.modules[name] = m
    return m
