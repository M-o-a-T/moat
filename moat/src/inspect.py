"""
This Trio inspector is geared towards figuring out why the *censored* a
task is cancelled when no exception shows up.
"""

from __future__ import annotations

import inspect
import logging

from asyncscope import scope as sc

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger("trio.inspect")


def debug(*a: Any) -> None:
    """logging helper"""
    s = sc.get()
    (logger if s is None else s.logger).debug(*a)


class CancelTracer:
    """A Trio inspect module that helps tracking cancel scopes"""

    # pylint: disable=missing-function-docstring,protected-access
    def __init__(self) -> None:
        pass

    def skip(self, scope: Any) -> bool:  # noqa: D102
        if scope._stack is None:  # noqa: SLF001
            return True
        if scope._stack[5].f_code.co_name == "connect_tcp":  # noqa: SLF001
            return True
        return False

    def scope_entered(self, scope: Any) -> None:  # noqa: D102
        scope._stack = s = []  # noqa: SLF001
        frame = inspect.currentframe()
        f = frame.f_back if frame is not None else None
        while f:
            s.append(f)
            f = f.f_back

        if self.skip(scope):
            return

        debug("EnterCS %r", scope)

    def scope_exited(self, scope: Any) -> None:  # noqa: D102
        if self.skip(scope):
            return
        debug("ExitCS %r", scope)

    def scope_cancelled(self, scope: Any, reason: Any) -> None:  # noqa: D102
        if self.skip(scope):
            return
        #       if reason.value == 0:
        #           breakpoint()
        debug("KillCS %r %s", scope, reason.name)

    def task_spawned(self, task: Any) -> None:  # noqa: D102
        debug("EnterT %r", task)

    def task_exited(self, task: Any) -> None:  # noqa: D102
        debug("ExitT %r", task)
