"""
This Trio inspector is geared towards figuring out why the *censored* a
task is cancelled when no exception shows up.

"""

from __future__ import annotations

import inspect
import logging

from asyncscope import scope as sc

logger = logging.getLogger("trio.inspect")


def debug(*a):
    "logging helper"
    s = sc.get()
    (logger if s is None else s.logger).debug(*a)


class CancelTracer:
    """A Trio inspect module that helps tracking cancel scopes"""

    # pylint: disable=missing-function-docstring,protected-access
    def __init__(self):
        pass

    def skip(self, scope):  # noqa: D102
        if scope._stack is None:  # noqa: SLF001
            return True
        if scope._stack[5].f_code.co_name == "connect_tcp":  # noqa: SLF001
            return True
        return False

    def scope_entered(self, scope):  # noqa: D102
        scope._stack = s = []  # noqa: SLF001
        f = inspect.currentframe().f_back
        while f:
            s.append(f)
            f = f.f_back

        if self.skip(scope):
            return

        debug("EnterCS %r", scope)

    def scope_exited(self, scope):  # noqa: D102
        if self.skip(scope):
            return
        debug("ExitCS %r", scope)

    def scope_cancelled(self, scope, reason):  # noqa: D102
        if self.skip(scope):
            return
        #       if reason.value == 0:
        #           breakpoint()
        debug("KillCS %r %s", scope, reason.name)

    def task_spawned(self, task):  # noqa: D102
        debug("EnterT %r", task)

    def task_exited(self, task):  # noqa: D102
        debug("ExitT %r", task)
