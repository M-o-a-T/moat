#!/usr/bin/python3

import sys
import os

import git
# assume that sys.path[0] is the main …/moat directory

def _get_sub(r):
    r = os.path.abspath(r)
    yield r
    rp = git.Repo(r)
    for rr in rp.submodules:
        yield from _get_sub(os.path.join(r,rr.path))

_pp = list(_get_sub(sys.path[0]))
sys.path[0:1] = _pp

os.environ["PYTHONPATH"] = os.pathsep.join(_pp)

import trio
import traceback
from outcome import Error

from moat.main import cmd
cmd()

async def main_():
    await main.main()

class Tracer(trio.abc.Instrument):
    def __init__(self):
        super().__init__()
        self.etasks=set()

    def _print_with_task(self, msg, task, err=None):
        # repr(task) is perhaps more useful than task.name in general,
        # but in context of a tutorial the extra noise is unhelpful.
        if err is not None:
            print("{}: {} {}".format(msg, task.name,repr(err)))
            traceback.print_exception(type(err),err,err.__traceback__)
        else:
            print("{}: {}".format(msg, task.name))

    def nursery_end(self, task, exception):
        if isinstance(exception,Exception):
            self.etasks.add(task)
            self._print_with_task("*** task excepted", task, exception)
        pass

    def before_task_step(self, task):
        if isinstance(task._next_send,Error) and isinstance(task._next_send.error, Exception):
            self._print_with_task("*** step resume ERROR", task, task._next_send.error)
            self.etasks.add(task)

    def task_exited(self, task):
        try:
            exception=task.outcome.error
        except AttributeError:
            exception=None
        if isinstance(exception,Exception):
            self._print_with_task("*** task excepted", task, exception)
        self.etasks.discard(task)

    def before_io_wait(self, timeout):
        if timeout>10000 and self.etasks:
            print("\n\n\n\n\n\n\n\n\n\n")
            print("*** ERROR: lock-out, killing off error tasks")
            print("\n\n\n\n")
            for t in self.etasks:
                if t._next_send_fn is None:
                    self._print_with_task("!!! Killing",t)
                    t._runner.reschedule(t,Error(RuntimeError("*** Locked ***")))
                else:
                    self._print_with_task("??? already scheduled",t)

#trio.run(main_, instruments=[Tracer()])


