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

    def skip(self, scope):
        if scope._stack is None:
            return True
        if scope._stack[5].f_code.co_name == "connect_tcp":
            return True
        return False

    def scope_entered(self, scope):
        scope._stack = s = []
        f = inspect.currentframe().f_back
        while f:
            s.append(f)
            f = f.f_back

        if self.skip(scope):
            return

        debug("EnterCS %r", scope)

    def scope_exited(self, scope):
        if self.skip(scope):
            return
        debug("ExitCS %r", scope)

    def scope_cancelled(self, scope, reason):
        if self.skip(scope):
            return
        #       if reason.value == 0:
        #           breakpoint()
        debug("KillCS %r %s", scope, reason.name)

    def task_spawned(self, task):
        debug("EnterT %r", task)

    def task_exited(self, task):
        debug("ExitT %r", task)
